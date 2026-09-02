"""/backlog — inspect the retest history (core/backlog/) for a target: the
last "beyond compare" diff, or the raw list of past snapshots. Read-only,
never touches Claude quota.
"""
from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import error_embed, simple_embed, truncate
from core.backlog.snapshot import list_snapshots


def setup(bot) -> None:
    group = app_commands.Group(name="backlog", description="Historico de testes (beyond compare) por alvo")

    @group.command(name="show", description="Ultimo diff (beyond compare) registrado para um alvo")
    async def backlog_show(interaction: discord.Interaction, target: str) -> None:
        snapshots = await list_snapshots(target, limit=1)
        if not snapshots:
            await interaction.response.send_message(
                embed=error_embed("Sem historico", f"Nenhum snapshot registrado ainda para `{target}` — rode `/recon` ou `/scan` primeiro.")
            )
            return

        latest = snapshots[0]
        embed = simple_embed(f"Backlog: {target}")
        embed.add_field(name="Ultimo teste", value=latest["created_at"], inline=False)
        embed.add_field(name="Achados no total", value=str(latest["total_findings"]), inline=True)
        embed.add_field(name="Novos desde o anterior", value=str(latest["new_since_last"]), inline=True)
        embed.add_field(name="Nao redetectados", value=str(latest["not_redetected_since_last"]), inline=True)
        embed.add_field(name="Resumo", value=truncate(latest["diff_summary"], 1000), inline=False)
        await interaction.response.send_message(embed=embed)

    @group.command(name="history", description="Lista os snapshots (testes) registrados para um alvo")
    async def backlog_history(interaction: discord.Interaction, target: str) -> None:
        snapshots = await list_snapshots(target, limit=20)
        if not snapshots:
            await interaction.response.send_message(
                embed=error_embed("Sem historico", f"Nenhum snapshot registrado ainda para `{target}`.")
            )
            return

        embed = simple_embed(f"Historico de testes: {target}")
        for s in snapshots:
            embed.add_field(
                name=s["created_at"],
                value=(
                    f"{s['total_findings']} achado(s) no total, "
                    f"{s['new_since_last']} novo(s), {s['not_redetected_since_last']} nao redetectado(s)"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    bot.tree.add_command(group)
