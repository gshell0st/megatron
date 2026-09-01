"""HackerOne hacker-facing API client — the only one of the three platforms
researched that has a real, documented endpoint for a researcher to both
read program scope AND submit a new report.

Auth: HTTP Basic, username = your H1 username, password = your API token
(Settings -> API Token on hackerone.com). Confirmed against
https://api.hackerone.com/hacker-reference/ and
https://api.hackerone.com/getting-started-hacker-api/ (2026).

Note: HackerOne requires the submitting account to have Signal >= 1.0 (a
platform-side reputation gate introduced Feb 2026) — that's an account
property we can't check or influence from here; a submission call will
simply fail with an API error if the account doesn't qualify.
"""
from __future__ import annotations

from typing import Any

import aiohttp

_BASE_URL = "https://api.hackerone.com/v1"


class HackerOneError(Exception):
    pass


async def _request(
    method: str, path: str, api_username: str, api_token: str, json_body: dict | None = None
) -> dict[str, Any]:
    auth = aiohttp.BasicAuth(api_username, api_token)
    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.request(
            method, f"{_BASE_URL}{path}", json=json_body, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise HackerOneError(f"HackerOne API {method} {path} -> {resp.status}: {body}")
            return body


async def fetch_scope(handle: str, api_username: str, api_token: str) -> list[dict[str, Any]]:
    """Returns a list of {platform_scope_id, domain, asset_type, eligible_for_submission}
    for every in-scope asset of a program, via GET .../hackers/programs/{handle}/structured_scopes."""
    body = await _request(
        "GET", f"/hackers/programs/{handle}/structured_scopes", api_username, api_token
    )
    results = []
    for item in body.get("data", []):
        attrs = item.get("attributes", {})
        asset_type = (attrs.get("asset_type") or "").upper()
        # Only URL/domain-shaped assets make sense as megatron scope.yaml
        # targets — skip source-code repos, mobile apps, hardware, etc.
        if asset_type not in ("URL", "WILDCARD", "DOMAIN", "OTHER"):
            continue
        results.append(
            {
                "platform_scope_id": int(item["id"]) if str(item.get("id", "")).isdigit() else item.get("id"),
                "domain": attrs.get("asset_identifier"),
                "asset_type": asset_type,
                "eligible_for_submission": attrs.get("eligible_for_submission", True),
                "max_severity": attrs.get("max_severity"),
            }
        )
    return results


async def submit_report(
    handle: str,
    api_username: str,
    api_token: str,
    title: str,
    impact: str,
    vulnerability_information: str,
    severity_rating: str | None = None,
    structured_scope_id: int | None = None,
) -> dict[str, Any]:
    """POST .../hackers/reports. Only called from bot/commands/submit_cmds.py
    after an explicit /submit confirm — never automatically."""
    attributes: dict[str, Any] = {
        "team_handle": handle,
        "title": title,
        "vulnerability_information": vulnerability_information,
        "impact": impact,
    }
    if severity_rating:
        attributes["severity_rating"] = severity_rating
    if structured_scope_id is not None:
        attributes["structured_scope_id"] = structured_scope_id

    body = await _request(
        "POST",
        "/hackers/reports",
        api_username,
        api_token,
        json_body={"data": {"type": "report", "attributes": attributes}},
    )
    data = body.get("data", {})
    return {"id": data.get("id"), "url": f"https://hackerone.com/reports/{data.get('id')}"}
