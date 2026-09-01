"""Intigriti researcher API client — read-only. Confirmed via the live
swagger spec (https://api.intigriti.com/external/researcher/swagger/v1/swagger.json,
2026) that this API has no submission endpoint for researchers; only
programs/domains/activities/payouts are exposed. Report submission for
Intigriti stays manual (via their web app) — do not add a submit_report()
here without re-verifying the API actually grew one.

Auth: Bearer token (Intigriti account -> researcher API token).
"""
from __future__ import annotations

from typing import Any

import aiohttp

_BASE_URL = "https://api.intigriti.com/external/researcher"


class IntigritiError(Exception):
    pass


async def _get(path: str, api_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(
            f"{_BASE_URL}{path}", timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise IntigritiError(f"Intigriti API GET {path} -> {resp.status}: {body}")
            return body


async def list_programs(api_token: str) -> list[dict[str, Any]]:
    body = await _get("/v1/programs", api_token)
    return body if isinstance(body, list) else body.get("records", body.get("data", []))


async def fetch_scope(program_id: str, api_token: str) -> list[dict[str, Any]]:
    """GET /v1/programs/{id} to find the current domains version id, then
    GET /v1/programs/{id}/domains/{versionId} for the actual scope items.
    Schema confirmed live: program.domains.id is the version id; the
    domains response is {"domains": {"content": [{"endpoint", "type", "tier", ...}]}}."""
    program = await _get(f"/v1/programs/{program_id}", api_token)
    version_id = (program.get("domains") or {}).get("id")
    if not version_id:
        raise IntigritiError(
            f"Program '{program_id}' response had no domains.id (version id) — "
            "Intigriti may have changed their API shape, check api.intigriti.com/external/researcher/swagger."
        )

    domains_resp = await _get(f"/v1/programs/{program_id}/domains/{version_id}", api_token)
    content = (domains_resp.get("domains") or {}).get("content", [])

    results = []
    for item in content:
        type_val = item.get("type")
        tier_val = item.get("tier")
        results.append(
            {
                "domain": item.get("endpoint"),
                "asset_type": type_val.get("value") if isinstance(type_val, dict) else type_val,
                "tier": tier_val.get("value") if isinstance(tier_val, dict) else tier_val,
            }
        )
    return results
