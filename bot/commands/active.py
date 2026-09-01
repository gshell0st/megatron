from __future__ import annotations

from urllib.parse import urlsplit

import discord
from discord import app_commands

from bot.formatting import error_embed, ok_embed
from core.audit import log as audit_log
from core.scope.validator import is_in_scope


def setup(bot) -> None:
    @bot.tree.command(
        name="scan",
        description="Scan ativo leve: ffuf (arquivos expostos), xss (dalfox) ou sqli (sqlmap)",
    )
    @app_commands.describe(
        target="Dominio cadastrado em /scope com mode=active",
        type="Tipo de scan",
        url="Obrigatorio para xss/sqli: URL completa com parametro (ex: https://alvo.com/page?id=1)",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="ffuf (arquivos/paths expostos)", value="ffuf"),
            app_commands.Choice(name="xss (dalfox)", value="xss"),
            app_commands.Choice(name="sqli (sqlmap)", value="sqli"),
        ]
    )
    async def scan(
        interaction: discord.Interaction,
        target: str,
        type: app_commands.Choice[str],
        url: str | None = None,
    ) -> None:
        entry = is_in_scope(target)
        if entry is None:
            await audit_log(str(interaction.user.id), "scope:reject", target=target)
            await interaction.response.send_message(
                embed=error_embed("Fora de escopo", f"`{target}` nao esta em scope.yaml."),
                ephemeral=True,
            )
            return
        if entry.mode != "active":
            await interaction.response.send_message(
                embed=error_embed(
                    "Scan ativo nao autorizado",
                    f"`{target}` esta cadastrado como `mode=passive` — use `/scope add` com "
                    f"`mode=active` primeiro se voce tem autorizacao pra isso.",
                ),
                ephemeral=True,
            )
            return

        job_type = type.value
        params: dict = {}

        if job_type in ("xss", "sqli"):
            if not url or not urlsplit(url).query:
                await interaction.response.send_message(
                    embed=error_embed(
                        "URL com parametro necessaria",
                        f"`/scan type:{job_type}` precisa de uma `url` com query string "
                        f"(ex: `https://{target}/page?id=1`) — sem parametro nao ha o que testar.",
                    ),
                    ephemeral=True,
                )
                return
            params["url"] = url

        job_id = await bot.job_queue.enqueue(
            job_type,
            target,
            created_by=str(interaction.user.id),
            channel_id=str(interaction.channel_id),
            params=params,
        )
        await interaction.response.send_message(
            embed=ok_embed(
                "Job enfileirado",
                f"`job #{job_id}` {job_type} em `{params.get('url', target)}`.",
            )
        )
