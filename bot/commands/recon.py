from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import error_embed, ok_embed
from core.audit import log as audit_log
from core.scope.validator import is_in_scope


def setup(bot) -> None:
    @bot.tree.command(
        name="recon",
        description="Roda recon passivo (subfinder -> httpx -> nuclei) em um alvo autorizado",
    )
    @app_commands.describe(target="Dominio ja cadastrado em /scope")
    async def recon(interaction: discord.Interaction, target: str) -> None:
        entry = is_in_scope(target)
        if entry is None:
            await audit_log(str(interaction.user.id), "scope:reject", target=target)
            await interaction.response.send_message(
                embed=error_embed("Fora de escopo", f"`{target}` nao esta em scope.yaml. Use `/scope add` primeiro."),
                ephemeral=True,
            )
            return

        job_id = await bot.job_queue.enqueue(
            "recon",
            target,
            created_by=str(interaction.user.id),
            channel_id=str(interaction.channel_id),
        )
        await interaction.response.send_message(
            embed=ok_embed(
                "Job enfileirado",
                f"`job #{job_id}` recon em `{target}` (mode={entry.mode}). "
                f"Progresso sera postado neste canal.",
            )
        )
