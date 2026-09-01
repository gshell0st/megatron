"""Embed builders and small text helpers shared by every command module."""
from __future__ import annotations

import discord

COLOR_OK = discord.Color.green()
COLOR_WARN = discord.Color.orange()
COLOR_ERROR = discord.Color.red()
COLOR_INFO = discord.Color.blurple()

SEVERITY_EMOJI = {
    "critical": "🟣",
    "high": "🔴",
    "medium": "🟠",
    "low": "🟡",
    "info": "⚪",
}


def truncate(text: str | None, limit: int = 1000) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def simple_embed(title: str, description: str = "", color: discord.Color = COLOR_INFO) -> discord.Embed:
    return discord.Embed(title=title, description=truncate(description, 4000), color=color)


def error_embed(title: str, description: str = "") -> discord.Embed:
    return simple_embed(f"❌ {title}", description, color=COLOR_ERROR)


def ok_embed(title: str, description: str = "") -> discord.Embed:
    return simple_embed(f"✅ {title}", description, color=COLOR_OK)


def findings_embed(target: str, rows: list, title: str = "Findings") -> discord.Embed:
    embed = simple_embed(f"{title}: {target}", color=COLOR_INFO)
    if not rows:
        embed.description = "Nenhum achado."
        return embed
    for row in rows[:20]:
        sev = (row["severity"] or "info").lower()
        emoji = SEVERITY_EMOJI.get(sev, "⚪")
        name = f"{emoji} [{row['status']}] {truncate(row['title'], 200)}"
        value = truncate(row["detail"] or row["url"] or "(sem detalhe)", 200)
        embed.add_field(name=name, value=value or "-", inline=False)
    if len(rows) > 20:
        embed.set_footer(text=f"Mostrando 20 de {len(rows)} achados.")
    return embed
