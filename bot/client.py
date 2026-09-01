"""Discord bot skeleton: owner-only + guild-locked command tree, job queue
wiring, and progress-message delivery back to the channel that started a job.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.audit import log as audit_log
from core.config import Settings
from core.jobs.models import get_job
from core.jobs.queue import JobQueue

logger = logging.getLogger("megatron.bot")


class OwnerOnlyTree(app_commands.CommandTree):
    """Every command in this tree is rejected for anyone but OWNER_DISCORD_ID,
    even if Discord permissions are misconfigured on the server side — this
    is the app-level half of the owner+guild lockdown safety rail."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot: MegatronBot = interaction.client  # type: ignore[assignment]
        if interaction.user.id != bot.settings.owner_discord_id:
            await audit_log(
                str(interaction.user.id),
                "command:reject_not_owner",
                details=f"command={interaction.command.qualified_name if interaction.command else '?'}",
            )
            await interaction.response.send_message(
                "Este bot so aceita comandos do dono configurado.", ephemeral=True
            )
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        logger.exception("command error", exc_info=error)
        message = f"Erro ao executar o comando: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


class MegatronBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, tree_cls=OwnerOnlyTree)
        self.settings = settings
        self.job_queue = JobQueue(settings)
        self.job_queue.set_progress_hook(self._on_job_progress)

    async def setup_hook(self) -> None:
        from bot.commands import findings_cmds, jobs_cmds, recon, scope_cmds, system_cmds

        scope_cmds.setup(self)
        recon.setup(self)
        jobs_cmds.setup(self)
        findings_cmds.setup(self)
        system_cmds.setup(self)

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        await self.job_queue.start()
        logger.info("Job queue started, commands synced to guild %s", self.settings.guild_id)

    async def close(self) -> None:
        await self.job_queue.stop()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (guild-locked to %s)", self.user, self.settings.guild_id)

    async def _on_job_progress(self, job_id: int, message: str) -> None:
        job = await get_job(job_id)
        if job is None:
            return
        try:
            channel = self.get_channel(int(job.channel_id)) or await self.fetch_channel(
                int(job.channel_id)
            )
            await channel.send(f"`job #{job_id}` {message}")  # type: ignore[union-attr]
        except (discord.HTTPException, ValueError):
            logger.warning("failed to post progress for job %s", job_id)
