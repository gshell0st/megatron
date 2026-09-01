from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import error_embed, findings_embed, ok_embed, simple_embed
from core.audit import log as audit_log
from core.claude_bridge import invoke as claude_invoke
from core.claude_bridge import quota as claude_quota
from core.claude_bridge.invoke import ClaudeInvocationError
from core.db import database
from core.findings.dedup import set_finding_status


def setup(bot) -> None:
    @bot.tree.command(name="findings", description="Lista achados de um alvo")
    @app_commands.describe(target="Dominio", severity="Filtra por severidade minima", status="Filtra por status")
    async def findings(
        interaction: discord.Interaction,
        target: str,
        severity: str | None = None,
        status: str | None = None,
    ) -> None:
        query = "SELECT * FROM findings WHERE target = ?"
        params: list = [target]
        if status:
            query += " AND status = ?"
            params.append(status)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        query += " ORDER BY id DESC LIMIT 100"

        rows = await database.fetchall(query, params)
        await interaction.response.send_message(embed=findings_embed(target, rows))

    @bot.tree.command(name="report", description="Gera um resumo escrito (1 chamada Claude) dos achados nao revisados de um alvo")
    async def report(interaction: discord.Interaction, target: str) -> None:
        rows = await database.fetchall(
            "SELECT id, target, tool, finding_type, severity, title, detail, url "
            "FROM findings WHERE target = ? AND status IN ('new', 'needs-review') "
            "ORDER BY id DESC LIMIT 40",
            (target,),
        )
        if not rows:
            await interaction.response.send_message(embed=simple_embed("Nada para reportar", f"Sem achados pendentes para `{target}`."))
            return

        if not await claude_quota.can_invoke():
            await interaction.response.send_message(
                embed=error_embed("Quota esgotada", "Orcamento diario do Claude esgotado. Tente novamente mais tarde ou ajuste com /system.")
            )
            return

        await interaction.response.defer()
        findings_list = [dict(r) for r in rows]
        try:
            result = await claude_invoke.report(bot.settings, target, findings_list)
        except ClaudeInvocationError as e:
            await audit_log(str(interaction.user.id), "claude:report_failed", target=target, error=str(e))
            await interaction.followup.send(embed=error_embed("Falha no report", str(e)))
            return

        for r in rows:
            await set_finding_status(r["id"], "reported")

        await audit_log(str(interaction.user.id), "claude:report_done", target=target, summary=result.get("summary"))
        embed = simple_embed(f"Report: {target}", result.get("summary", "(sem resumo)"))
        await interaction.followup.send(embed=embed)
