"""TLS/certificate configuration check via sslyze (pip package `sslyze`).
Requires mode=active — a full TLS handshake probe across every protocol
version is a distinct signal from the plain HTTP requests recon already
makes. Parsing is defensive throughout: sslyze's JSON schema isn't
guaranteed stable across versions, so every lookup degrades to "skip this
sub-check" rather than crashing the job if a field is missing/renamed.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from core.scope.loader import ScopeEntry
from core.tools.base import ToolWrapper

_INSECURE_PROTOCOLS = {
    "ssl_2_0_cipher_suites": ("SSLv2", "critical"),
    "ssl_3_0_cipher_suites": ("SSLv3", "critical"),
    "tls_1_0_cipher_suites": ("TLSv1.0", "medium"),
    "tls_1_1_cipher_suites": ("TLSv1.1", "medium"),
}
_MIN_KEY_SIZE = 112  # bits; below this a cipher is considered weak regardless of name


def _host_for(target: str) -> str:
    if "://" in target:
        target = urlsplit(target).netloc or target
    return target.split("/")[0]


class TlsScanTool(ToolWrapper):
    name = "sslyze"
    default_timeout = 120

    def build_command(self, tool_path: str, target: str, scope: ScopeEntry, job_id: int) -> list[str]:
        return [tool_path, "--json_out=-", _host_for(target)]

    def parse_output(self, raw_stdout: str) -> list[dict[str, Any]]:
        try:
            envelope = json.loads(raw_stdout)
        except json.JSONDecodeError:
            return []

        results = envelope.get("server_scan_results") or []
        if not results:
            return []
        server = results[0]
        hostname = ((server.get("server_location") or {}).get("hostname")) or ""
        scan_result = server.get("scan_result") or {}

        findings: list[dict[str, Any]] = []

        for cmd_key, (label, severity) in _INSECURE_PROTOCOLS.items():
            entry = scan_result.get(cmd_key) or {}
            result = entry.get("result") or {}
            supported = result.get("is_tls_version_supported")
            if supported is None:
                supported = bool(result.get("accepted_cipher_suites"))
            if supported:
                findings.append(
                    {
                        "finding_type": "vuln",
                        "severity": severity,
                        "title": f"Protocolo TLS inseguro habilitado: {label}",
                        "detail": f"{hostname}: servidor aceita {label}",
                        "url": None,
                    }
                )

        weak_ciphers: set[str] = set()
        for cmd_key in (
            "tls_1_0_cipher_suites", "tls_1_1_cipher_suites", "tls_1_2_cipher_suites", "tls_1_3_cipher_suites",
        ):
            result = (scan_result.get(cmd_key) or {}).get("result") or {}
            for accepted in result.get("accepted_cipher_suites") or []:
                suite = accepted.get("cipher_suite") or {}
                name = suite.get("name") or suite.get("openssl_name")
                if not name:
                    continue
                if suite.get("is_anonymous") or (suite.get("key_size") and suite["key_size"] < _MIN_KEY_SIZE):
                    weak_ciphers.add(name)
        if weak_ciphers:
            findings.append(
                {
                    "finding_type": "vuln",
                    "severity": "high",
                    "title": "Cipher suite(s) fraca(s) aceita(s)",
                    "detail": f"{hostname}: {', '.join(sorted(weak_ciphers))[:400]}",
                    "url": None,
                }
            )

        heartbleed = ((scan_result.get("heartbleed") or {}).get("result") or {})
        if heartbleed.get("is_vulnerable_to_heartbleed"):
            findings.append(
                {
                    "finding_type": "vuln",
                    "severity": "critical",
                    "title": "Vulneravel a Heartbleed (CVE-2014-0160)",
                    "detail": hostname,
                    "url": None,
                }
            )

        robot = ((scan_result.get("robot") or {}).get("result") or {})
        robot_status = str(robot.get("robot_result") or robot.get("robot_result_enum") or "")
        if robot_status and "NOT_VULNERABLE" not in robot_status.upper() and "VULNERABLE" in robot_status.upper():
            findings.append(
                {
                    "finding_type": "vuln",
                    "severity": "high",
                    "title": "Possivelmente vulneravel a ROBOT (Bleichenbacher/RSA oracle)",
                    "detail": f"{hostname}: {robot_status}",
                    "url": None,
                }
            )

        cert_result = ((scan_result.get("certificate_info") or {}).get("result") or {})
        for deployment in cert_result.get("certificate_deployments") or []:
            validations = deployment.get("path_validation_results") or []
            if validations and not any(v.get("was_validation_successful") for v in validations):
                first_error = validations[0].get("validation_error") or "validacao falhou em todas as trust stores testadas"
                findings.append(
                    {
                        "finding_type": "vuln",
                        "severity": "medium",
                        "title": "Certificado TLS nao confia em nenhuma trust store testada",
                        "detail": f"{hostname}: {first_error} (self-signed, expirado ou cadeia incompleta)",
                        "url": None,
                    }
                )
                break

        return findings
