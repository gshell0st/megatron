from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import error_embed, ok_embed, simple_embed
from core.audit import log as audit_log
from core.jobs.models import get_job, list_jobs


def setup(bot) -> None:
    group = app_commands.Group(name="jobs", description="Status e controle de jobs")

    @group.command(name="status", description="Lista jobs recentes ou mostra o detalhe de um")
    async def jobs_status(interaction: discord.Interaction, job_id: int | None = None) -> None:
        if job_id is not None:
            job = await get_job(job_id)
            if job is None:
                await interaction.response.send_message(embed=error_embed("Nao encontrado", f"job #{job_id} nao existe."))
                return
            embed = simple_embed(f"Job #{job.id} — {job.job_type} — {job.target}")
            embed.add_field(name="status", value=job.status, inline=True)
            embed.add_field(name="criado por", value=job.created_by, inline=True)
            embed.add_field(name="criado em", value=job.created_at, inline=False)
            if job.error:
                embed.add_field(name="erro", value=job.error, inline=False)
            await interaction.response.send_message(embed=embed)
            return

        jobs = await list_jobs(limit=10)
        if not jobs:
            await interaction.response.send_message(embed=simple_embed("Jobs", "Nenhum job ainda."))
            return
        embed = simple_embed("Jobs recentes")
        for j in jobs:
            embed.add_field(name=f"#{j.id} {j.job_type} — {j.target}", value=f"status={j.status}", inline=False)
        await interaction.response.send_message(embed=embed)

    @group.command(name="cancel", description="Cancela um job em fila ou em execucao")
    async def jobs_cancel(interaction: discord.Interaction, job_id: int) -> None:
        cancelled = await bot.job_queue.cancel(job_id)
        await audit_log(str(interaction.user.id), "job:cancel", job_id=job_id, success=cancelled)
        if cancelled:
            await interaction.response.send_message(embed=ok_embed("Cancelado", f"job #{job_id} cancelado."))
        else:
            await interaction.response.send_message(embed=error_embed("Nao cancelado", f"job #{job_id} nao esta queued/running."))

    bot.tree.add_command(group)
