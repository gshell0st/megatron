from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import ok_embed, simple_embed
from core.audit import log as audit_log
from core.claude_bridge import quota as claude_quota
from core.db import database


def setup(bot) -> None:
    @bot.tree.command(name="quota", description="Mostra o uso diario de invocacoes do Claude")
    async def quota_cmd(interaction: discord.Interaction) -> None:
        used = await claude_quota.invocations_last_24h()
        budget = await claude_quota.get_daily_budget()
        embed = simple_embed(
            "Quota do Claude (24h)",
            f"{used} / {budget} invocacoes\nbackend={bot.settings.claude_backend}",
        )
        await interaction.response.send_message(embed=embed)

    group = app_commands.Group(name="system", description="Controles globais do megatron")

    @group.command(name="pause", description="Pausa o processamento de novos jobs (kill switch)")
    async def system_pause(interaction: discord.Interaction) -> None:
        await database.set_setting("paused", "1")
        await audit_log(str(interaction.user.id), "system:pause")
        await interaction.response.send_message(embed=ok_embed("Pausado", "Nenhum job novo sera iniciado ate /system resume."))

    @group.command(name="resume", description="Retoma o processamento de jobs")
    async def system_resume(interaction: discord.Interaction) -> None:
        await database.set_setting("paused", "0")
        await audit_log(str(interaction.user.id), "system:resume")
        await interaction.response.send_message(embed=ok_embed("Retomado", "Jobs voltam a ser processados."))

    bot.tree.add_command(group)
