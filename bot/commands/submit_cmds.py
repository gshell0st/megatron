"""/submit — draft-then-confirm report submission. HackerOne only: it's the
only platform researched here with a real researcher-facing submission API
(see core/platforms/hackerone.py). There is deliberately no path that sends
a report without an explicit /submit confirm — that's the model the owner
chose over auto-submission.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import discord
from discord import app_commands

from bot.formatting import error_embed, ok_embed, simple_embed, truncate
from core.audit import log as audit_log
from core.claude_bridge.invoke import ClaudeInvocationError, draft_submission
from core.db import database
from core.findings.dedup import set_finding_status
from core.platforms.hackerone import HackerOneError
from core.platforms.hackerone import submit_report as h1_submit_report
from core.scope.validator import is_in_scope

_REQUIRED_DRAFT_FIELDS = ("title", "impact", "vulnerability_information", "severity_rating")


def setup(bot) -> None:
    group = app_commands.Group(name="submit", description="Rascunho e envio de report (HackerOne)")

    @group.command(name="draft", description="Gera um rascunho de report a partir de achados priorizados")
    async def submit_draft(interaction: discord.Interaction, target: str) -> None:
        entry = is_in_scope(target)
        if entry is None or entry.platform != "hackerone" or not entry.program_handle:
            await interaction.response.send_message(
                embed=error_embed(
                    "Alvo sem plataforma vinculada",
                    f"`{target}` precisa estar no scope.yaml com `platform: hackerone` e "
                    f"`program_handle` definidos (via `/scope import platform:hackerone` ou "
                    f"editando scope.yaml manualmente).",
                ),
                ephemeral=True,
            )
            return

        rows = await database.fetchall(
            "SELECT id, target, tool, finding_type, severity, title, detail, url "
            "FROM findings WHERE target = ? AND status = 'reviewed-priority' "
            "ORDER BY id DESC LIMIT 10",
            (target,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=simple_embed(
                    "Nada pra rascunhar",
                    f"Sem achados com status `reviewed-priority` pra `{target}`. "
                    f"Rode `/recon` ou `/scan` e espere a triagem do Claude primeiro.",
                )
            )
            return

        if not (bot.settings.hackerone_api_username and bot.settings.hackerone_api_token):
            await interaction.response.send_message(
                embed=error_embed(
                    "Credenciais faltando",
                    "Configure HACKERONE_API_USERNAME e HACKERONE_API_TOKEN no .env antes de "
                    "rascunhar (precisamos delas em /submit confirm; ok gerar o rascunho sem "
                    "elas, mas o confirm vai falhar).",
                )
            )

        await interaction.response.defer()
        findings_list = [dict(r) for r in rows]
        try:
            draft = await draft_submission(bot.settings, target, findings_list)
        except ClaudeInvocationError as e:
            await audit_log(str(interaction.user.id), "submit:draft_failed", target=target, error=str(e))
            await interaction.followup.send(embed=error_embed("Falha ao gerar rascunho", str(e)))
            return

        missing = [f for f in _REQUIRED_DRAFT_FIELDS if not draft.get(f)]
        if missing:
            await interaction.followup.send(
                embed=error_embed(
                    "Rascunho incompleto",
                    f"Claude nao retornou os campos {missing} — tente de novo. "
                    f"Resposta bruta salva em data/logs/claude_raw/.",
                )
            )
            return

        finding_ids = [r["id"] for r in rows]
        draft_id = await database.execute(
            "INSERT INTO report_drafts "
            "(finding_ids_json, target, platform, program_handle, title, impact, "
            "vulnerability_information, severity_rating, status, created_by, created_at) "
            "VALUES (?, ?, 'hackerone', ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                json.dumps(finding_ids),
                target,
                entry.program_handle,
                draft["title"],
                draft["impact"],
                draft["vulnerability_information"],
                draft["severity_rating"],
                str(interaction.user.id),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await audit_log(str(interaction.user.id), "submit:draft_created", target=target, job_id=None, draft_id=draft_id)

        embed = simple_embed(f"Rascunho #{draft_id} — {entry.program_handle} (HackerOne)")
        embed.add_field(name="Titulo", value=truncate(draft["title"], 250), inline=False)
        embed.add_field(name="Impacto", value=truncate(draft["impact"], 1000), inline=False)
        embed.add_field(name="Severidade", value=draft["severity_rating"], inline=True)
        embed.add_field(
            name="Detalhes/reproducao",
            value=truncate(draft["vulnerability_information"], 1000),
            inline=False,
        )
        embed.set_footer(text=f"Revise com cuidado. Envie com /submit confirm draft_id:{draft_id}")
        await interaction.followup.send(embed=embed)

    @group.command(name="confirm", description="Envia um rascunho pendente pro HackerOne de verdade")
    async def submit_confirm(interaction: discord.Interaction, draft_id: int) -> None:
        row = await database.fetchone("SELECT * FROM report_drafts WHERE id = ?", (draft_id,))
        if row is None:
            await interaction.response.send_message(embed=error_embed("Nao encontrado", f"Rascunho #{draft_id} nao existe."))
            return
        if row["status"] != "pending":
            await interaction.response.send_message(
                embed=error_embed("Ja processado", f"Rascunho #{draft_id} esta com status `{row['status']}`.")
            )
            return
        if not (bot.settings.hackerone_api_username and bot.settings.hackerone_api_token):
            await interaction.response.send_message(
                embed=error_embed("Credenciais faltando", "Configure HACKERONE_API_USERNAME/TOKEN no .env.")
            )
            return

        entry = is_in_scope(row["target"])
        structured_scope_id = entry.platform_scope_id if entry else None

        await interaction.response.defer()
        try:
            result = await h1_submit_report(
                row["program_handle"],
                bot.settings.hackerone_api_username,
                bot.settings.hackerone_api_token,
                title=row["title"],
                impact=row["impact"],
                vulnerability_information=row["vulnerability_information"],
                severity_rating=row["severity_rating"],
                structured_scope_id=structured_scope_id,
            )
        except HackerOneError as e:
            await audit_log(str(interaction.user.id), "submit:confirm_failed", target=row["target"], draft_id=draft_id, error=str(e))
            await interaction.followup.send(embed=error_embed("Falha no envio ao HackerOne", str(e)))
            return

        now = datetime.now(timezone.utc).isoformat()
        await database.execute(
            "UPDATE report_drafts SET status='submitted', submitted_at=?, external_report_id=?, external_report_url=? WHERE id=?",
            (now, result.get("id"), result.get("url"), draft_id),
        )
        for finding_id in json.loads(row["finding_ids_json"]):
            await set_finding_status(finding_id, "reported")

        await audit_log(
            str(interaction.user.id), "submit:confirmed", target=row["target"], draft_id=draft_id, external_id=result.get("id")
        )
        await interaction.followup.send(
            embed=ok_embed("Enviado ao HackerOne", f"Report criado: {result.get('url', result.get('id'))}")
        )

    @group.command(name="list", description="Lista rascunhos de report")
    async def submit_list(interaction: discord.Interaction, status: str = "pending") -> None:
        rows = await database.fetchall(
            "SELECT id, target, platform, program_handle, title, status FROM report_drafts "
            "WHERE status = ? ORDER BY id DESC LIMIT 20",
            (status,),
        )
        if not rows:
            await interaction.response.send_message(embed=simple_embed("Rascunhos", f"Nenhum com status `{status}`."))
            return
        embed = simple_embed(f"Rascunhos ({status})")
        for r in rows:
            embed.add_field(
                name=f"#{r['id']} — {r['target']}",
                value=f"{r['platform']}/{r['program_handle']}: {truncate(r['title'], 150)}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @group.command(name="discard", description="Descarta um rascunho pendente sem enviar")
    async def submit_discard(interaction: discord.Interaction, draft_id: int) -> None:
        row = await database.fetchone("SELECT status FROM report_drafts WHERE id = ?", (draft_id,))
        if row is None or row["status"] != "pending":
            await interaction.response.send_message(
                embed=error_embed("Nao aplicavel", f"Rascunho #{draft_id} nao existe ou nao esta pendente.")
            )
            return
        await database.execute("UPDATE report_drafts SET status='discarded' WHERE id=?", (draft_id,))
        await audit_log(str(interaction.user.id), "submit:discarded", draft_id=draft_id)
        await interaction.response.send_message(embed=ok_embed("Descartado", f"Rascunho #{draft_id} descartado."))

    bot.tree.add_command(group)
