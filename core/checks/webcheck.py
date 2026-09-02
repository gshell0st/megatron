"""The 9 "web hygiene" checks that don't need a subprocess tool: security
headers, cookie flags, directory listing, and body-confirmed exposure of
git/.env/backups/swagger/actuator/graphql. Each check hits a short, curated
path list (never a generic brute-force wordlist) and every hit is verified
against a per-host soft-404 baseline before being trusted — a custom "not
found" page that answers 200 is the single biggest source of false
positives for path-probing checks like these, so this is not optional.

Findings use finding_type='exposure' only where the body was actually
inspected and looks genuinely sensitive (secrets found, actuator dump,
confirmed git repo, dangerous GraphQL mutation) — that's what lets
core/findings/severity.py's get_triage_candidates() forward them to Claude
regardless of severity. Everything else (headers/cookies/dir-listing/plain
swagger) is scored by severity and only reaches Claude if it clears the
normal medium+ bar, keeping low-signal noise out of the one triage call.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import aiohttp

from core.checks.secrets import find_secrets
from core.scope.loader import ScopeEntry

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
_MAX_BODY_BYTES = 200_000  # enough for a .env/config/swagger doc, not a full backup archive

_GIT_PATHS = ("/.git/HEAD", "/.git/config")
_ENV_PATHS = ("/.env", "/.env.local", "/.env.production", "/.env.backup", "/.env.example")
_BACKUP_PATHS = (
    "/backup.zip", "/backup.sql", "/backup.tar.gz", "/dump.sql", "/database.sql",
    "/db.sqlite3", "/config.php.bak", "/config.php.old", "/web.config",
    "/wp-config.php.bak", "/docker-compose.yml", "/docker-compose.override.yml",
)
_SWAGGER_PATHS = (
    "/swagger.json", "/swagger-ui.html", "/api-docs", "/api/swagger.json",
    "/openapi.json", "/v2/api-docs", "/v3/api-docs", "/swagger/v1/swagger.json",
)
_ACTUATOR_SEVERITY = {
    "/actuator/env": "critical",
    "/actuator/heapdump": "critical",
    "/actuator/configprops": "high",
    "/actuator/beans": "medium",
    "/actuator/threaddump": "medium",
    "/actuator/mappings": "low",
    "/actuator/loggers": "low",
    "/debug": "medium",
    "/phpinfo.php": "medium",
    "/info.php": "low",
    "/_profiler": "low",
}
_DIR_LISTING_PATHS = ("/", "/images/", "/uploads/", "/backup/", "/files/", "/assets/")
_GRAPHQL_PATHS = ("/graphql", "/api/graphql", "/graphiql", "/v1/graphql", "/query")
_SECURITY_HEADERS = {
    "content-security-policy": "medium",
    "strict-transport-security": "medium",  # only scored when the base URL is https
    "x-content-type-options": "low",
    "x-frame-options": "low",
    "referrer-policy": "low",
    "permissions-policy": "low",
}
_SENSITIVE_COOKIE_HINTS = ("sess", "auth", "token", "sid", "jwt", "login")
_DANGEROUS_GRAPHQL_KEYWORDS = ("delete", "remove", "reset", "grant", "impersonate", "admin", "drop")

_INTROSPECTION_QUERY = {
    "query": (
        "query IntrospectionQuery { __schema { queryType { name } mutationType { name } "
        "types { name kind fields { name } } } }"
    )
}


@dataclass
class Probe:
    status: int
    headers: dict[str, str]
    set_cookies: list[str]
    body: str


async def _fetch(
    session: aiohttp.ClientSession, url: str, method: str = "GET", json_body: dict | None = None
) -> Probe | None:
    try:
        async with session.request(
            method, url, json=json_body, timeout=_REQUEST_TIMEOUT, allow_redirects=False
        ) as resp:
            raw = await resp.content.read(_MAX_BODY_BYTES)
            body = raw.decode(errors="replace")
            return Probe(
                status=resp.status,
                headers={k.lower(): v for k, v in resp.headers.items()},
                set_cookies=resp.headers.getall("Set-Cookie", []),
                body=body,
            )
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError):
        return None


def _base_url(target: str) -> str:
    if target.startswith("http://") or target.startswith("https://"):
        return target.rstrip("/")
    return f"https://{target}".rstrip("/")


def _is_excluded(path: str, excluded_paths: tuple[str, ...]) -> bool:
    stripped = path.lstrip("/")
    return any(stripped.startswith(p.lstrip("/")) for p in excluded_paths)


async def _soft_404_baseline(session: aiohttp.ClientSession, base_url: str) -> tuple[int, str]:
    """A custom "not found" page that answers 200 is the single biggest
    false-positive source for path-probing checks — comparing status alone
    isn't enough. Body *content* similarity (not just length) is what
    actually distinguishes a templated 404 from a short-but-real hit (a
    minimal .env or a compact JSON actuator response can coincidentally be
    about the same length as a site's 404 page)."""
    probe = await _fetch(session, f"{base_url}/{uuid4().hex}-not-a-real-path")
    if probe is None:
        return 404, ""
    return probe.status, probe.body


def _looks_real(probe: Probe | None, baseline: tuple[int, str]) -> bool:
    if probe is None or probe.status not in (200, 201):
        return False
    base_status, base_body = baseline
    if probe.status != base_status:
        return True
    if probe.body == base_body:
        return False
    ratio = SequenceMatcher(None, probe.body[:2000], base_body[:2000]).quick_ratio()
    return ratio <= 0.85


class WebCheckRunner:
    def __init__(self, target: str, scope: ScopeEntry):
        self.target = target
        self.base_url = _base_url(target)
        self.excluded_paths = scope.excluded_paths
        self._delay = 1.0 / max(scope.rate_limit_rps, 1.0)
        self.findings: list[dict[str, Any]] = []
        self.git_confirmed = False

    def _add(self, finding_type: str, severity: str, title: str, detail: str, url: str) -> None:
        self.findings.append(
            {"finding_type": finding_type, "severity": severity, "title": title, "detail": detail, "url": url}
        )

    async def _throttled_probe(self, session: aiohttp.ClientSession, path: str) -> tuple[str, Probe | None]:
        await asyncio.sleep(self._delay)
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        return path, await _fetch(session, url)

    async def run(self) -> tuple[list[dict[str, Any]], bool]:
        async with aiohttp.ClientSession() as session:
            baseline = await self._soft_404(session)
            base_probe = await _fetch(session, self.base_url)
            if base_probe is not None:
                self._check_headers(base_probe)
                self._check_cookies(base_probe)
            await self._check_directory_listing(session, baseline)
            await self._check_git(session, baseline)
            await self._check_env_secrets(session, baseline)
            await self._check_backups(session, baseline)
            await self._check_swagger(session, baseline)
            await self._check_actuator(session, baseline)
            await self._check_graphql(session)
        return self.findings, self.git_confirmed

    async def _soft_404(self, session: aiohttp.ClientSession) -> tuple[int, str]:
        await asyncio.sleep(self._delay)
        return await _soft_404_baseline(session, self.base_url)

    def _check_headers(self, probe: Probe) -> None:
        is_https = self.base_url.startswith("https://")
        missing = []
        for header, severity in _SECURITY_HEADERS.items():
            if header == "strict-transport-security" and not is_https:
                continue
            if header not in probe.headers:
                missing.append((header, severity))
        if not missing:
            return
        worst = "medium" if any(s == "medium" for _, s in missing) and len(missing) >= 2 else (
            "medium" if len(missing) >= 4 else "low"
        )
        names = ", ".join(h for h, _ in missing)
        self._add(
            "http-hygiene",
            worst,
            f"Security headers ausentes em {self.base_url}",
            f"faltando: {names}",
            self.base_url,
        )

    def _check_cookies(self, probe: Probe) -> None:
        is_https = self.base_url.startswith("https://")
        for raw in probe.set_cookies:
            name = raw.split("=", 1)[0].strip()
            lower = raw.lower()
            missing = []
            if is_https and "secure" not in lower:
                missing.append("Secure")
            if "httponly" not in lower:
                missing.append("HttpOnly")
            if "samesite" not in lower:
                missing.append("SameSite")
            if not missing:
                continue
            sensitive = any(hint in name.lower() for hint in _SENSITIVE_COOKIE_HINTS)
            severity = "medium" if sensitive else "low"
            self._add(
                "http-hygiene",
                severity,
                f"Cookie mal configurado: {name}",
                f"faltando: {', '.join(missing)} (cookie {'parece de sessao/auth' if sensitive else 'comum'})",
                self.base_url,
            )

    async def _check_directory_listing(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path in _DIR_LISTING_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if probe is None or probe.status != 200:
                continue
            if re.search(r"Index of /|<title>Index of|Directory listing for", probe.body, re.IGNORECASE):
                url = urljoin(self.base_url + "/", path.lstrip("/"))
                self._add(
                    "http-hygiene",
                    "medium" if path != "/" else "low",
                    f"Directory listing habilitado: {url}",
                    "resposta contem marcador de listagem de diretorio",
                    url,
                )

    async def _check_git(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path in _GIT_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if not _looks_real(probe, baseline):
                continue
            body_head = probe.body[:200]
            is_real = (path.endswith("HEAD") and body_head.strip().startswith("ref:")) or (
                path.endswith("config") and "[core]" in body_head
            )
            if not is_real:
                continue
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            self.git_confirmed = True
            self._add(
                "exposure",
                "high",
                f"Repositorio .git exposto em {self.base_url}",
                f"confirmado via {path} — possivel reconstrucao completa do codigo-fonte/historico",
                url,
            )
            return  # one confirmation is enough; pipeline decides whether to dump

    async def _check_env_secrets(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path in _ENV_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if not _looks_real(probe, baseline):
                continue
            if "<html" in probe.body[:200].lower():
                continue
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            secrets = find_secrets(probe.body)
            if secrets:
                kinds = ", ".join(sorted({s["kind"] for s in secrets}))
                self._add(
                    "exposure",
                    "critical",
                    f"Secrets em arquivo exposto: {path}",
                    f"tipos encontrados: {kinds} — ex: {secrets[0]['excerpt']}",
                    url,
                )
            else:
                self._add(
                    "exposure",
                    "medium",
                    f"Arquivo de ambiente/config exposto: {path}",
                    "arquivo acessivel publicamente, nenhum padrao de secret conhecido bateu — revisar manualmente",
                    url,
                )

    async def _check_backups(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path in _BACKUP_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if not _looks_real(probe, baseline):
                continue
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            self._add(
                "exposure",
                "high",
                f"Backup/config exposto: {path}",
                f"tamanho da resposta={len(probe.body)} bytes — download publico possivel",
                url,
            )

    async def _check_swagger(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path in _SWAGGER_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if not _looks_real(probe, baseline):
                continue
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            try:
                doc = json.loads(probe.body)
            except json.JSONDecodeError:
                if "swagger" not in probe.body.lower() and "openapi" not in probe.body.lower():
                    continue
                self._add("exposure", "low", f"Swagger/OpenAPI UI exposto: {path}", "pagina de UI, sem doc JSON parseavel", url)
                continue
            paths = list((doc.get("paths") or {}).keys())
            interesting = [p for p in paths if re.search(r"admin|internal|debug|manage|user|account", p, re.IGNORECASE)]
            severity = "medium" if interesting else "low"
            detail = f"{len(paths)} endpoint(s) documentado(s)"
            if interesting:
                detail += f"; possivelmente sensiveis: {', '.join(interesting[:5])}"
            self._add("exposure" if interesting else "endpoint", severity, f"Swagger/OpenAPI exposto: {path}", detail, url)

    async def _check_actuator(self, session: aiohttp.ClientSession, baseline: tuple[int, str]) -> None:
        for path, severity in _ACTUATOR_SEVERITY.items():
            if _is_excluded(path, self.excluded_paths):
                continue
            _, probe = await self._throttled_probe(session, path)
            if not _looks_real(probe, baseline):
                continue
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            self._add(
                "exposure" if severity in ("critical", "high") else "endpoint",
                severity,
                f"Endpoint de debug/actuator exposto: {path}",
                f"resposta {probe.status}, {len(probe.body)} bytes",
                url,
            )

    async def _check_graphql(self, session: aiohttp.ClientSession) -> None:
        for path in _GRAPHQL_PATHS:
            if _is_excluded(path, self.excluded_paths):
                continue
            await asyncio.sleep(self._delay)
            url = urljoin(self.base_url + "/", path.lstrip("/"))
            probe = await _fetch(session, url, method="POST", json_body=_INTROSPECTION_QUERY)
            if probe is None or probe.status not in (200, 400):
                continue
            try:
                data = json.loads(probe.body)
            except json.JSONDecodeError:
                continue
            schema = (data.get("data") or {}).get("__schema") if isinstance(data, dict) else None
            if not schema:
                continue

            mutation_type_name = (schema.get("mutationType") or {}).get("name")
            mutation_fields: list[str] = []
            for t in schema.get("types") or []:
                if t.get("name") == mutation_type_name:
                    mutation_fields = [f.get("name", "") for f in (t.get("fields") or [])]
                    break
            dangerous = [
                f for f in mutation_fields if any(kw in f.lower() for kw in _DANGEROUS_GRAPHQL_KEYWORDS)
            ]
            type_count = len(schema.get("types") or [])
            if dangerous:
                self._add(
                    "exposure",
                    "high",
                    f"GraphQL introspection habilitada com mutations sensiveis: {path}",
                    f"{type_count} tipos no schema; mutations suspeitas: {', '.join(dangerous[:8])}",
                    url,
                )
            else:
                self._add(
                    "endpoint",
                    "low",
                    f"GraphQL introspection habilitada: {path}",
                    f"{type_count} tipos no schema, {len(mutation_fields)} mutation(s) — nenhuma claramente perigosa pelo nome",
                    url,
                )
            return  # one confirmed introspection-enabled endpoint is enough signal


async def run_web_checks(target: str, scope: ScopeEntry) -> tuple[list[dict[str, Any]], bool]:
    """Returns (findings, git_confirmed) — git_confirmed tells the pipeline
    whether it's worth spending a git-dumper run on this target."""
    runner = WebCheckRunner(target, scope)
    return await runner.run()
