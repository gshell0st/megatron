from __future__ import annotations

import discord
from discord import app_commands

from bot.formatting import error_embed, ok_embed, simple_embed
from core.audit import log as audit_log
from core.platforms.hackerone import HackerOneError
from core.platforms.hackerone import fetch_scope as h1_fetch_scope
from core.platforms.intigriti import IntigritiError
from core.platforms.intigriti import fetch_scope as intigriti_fetch_scope
from core.scope.loader import get_scope_store


def setup(bot) -> None:
    group = app_commands.Group(name="scope", description="Gerencia o escopo autorizado (scope.yaml)")

    @group.command(name="list", description="Lista os alvos autorizados")
    async def scope_list(interaction: discord.Interaction) -> None:
        entries = get_scope_store().list()
        if not entries:
            await interaction.response.send_message(embed=simple_embed("Escopo vazio", "Nenhum alvo cadastrado ainda."))
            return
        embed = simple_embed("Alvos autorizados")
        for e in entries:
            embed.add_field(
                name=f"{e.domain} ({e.mode})",
                value=f"rate_limit={e.rate_limit_rps}rps  excluded={list(e.excluded_paths) or '-'}\n{e.notes or ''}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @group.command(name="add", description="Adiciona ou atualiza um alvo no escopo")
    @app_commands.describe(domain="Dominio raiz autorizado", mode="passive ou active", rate_limit_rps="Requisicoes/seg maximas")
    @app_commands.choices(mode=[
        app_commands.Choice(name="passive (so recon)", value="passive"),
        app_commands.Choice(name="active (permite /scan)", value="active"),
    ])
    async def scope_add(
        interaction: discord.Interaction,
        domain: str,
        mode: app_commands.Choice[str],
        rate_limit_rps: float = 5.0,
        notes: str = "",
    ) -> None:
        get_scope_store().add(domain, mode=mode.value, rate_limit_rps=rate_limit_rps, notes=notes)
        await audit_log(str(interaction.user.id), "scope:add", target=domain, mode=mode.value, rate_limit_rps=rate_limit_rps)
        await interaction.response.send_message(
            embed=ok_embed("Escopo atualizado", f"`{domain}` -> mode={mode.value}, rate_limit={rate_limit_rps}rps")
        )

    @group.command(name="remove", description="Remove um alvo do escopo")
    async def scope_remove(interaction: discord.Interaction, domain: str) -> None:
        removed = get_scope_store().remove(domain)
        await audit_log(str(interaction.user.id), "scope:remove", target=domain, removed=removed)
        if removed:
            await interaction.response.send_message(embed=ok_embed("Removido", f"`{domain}` nao esta mais no escopo."))
        else:
            await interaction.response.send_message(embed=error_embed("Nao encontrado", f"`{domain}` nao estava no escopo."))

    @group.command(name="reload", description="Recarrega scope.yaml do disco")
    async def scope_reload(interaction: discord.Interaction) -> None:
        get_scope_store().reload()
        await audit_log(str(interaction.user.id), "scope:reload")
        await interaction.response.send_message(embed=ok_embed("Recarregado", "scope.yaml recarregado do disco."))

    @group.command(name="import", description="Importa escopo de um programa via API (leitura apenas)")
    @app_commands.describe(
        handle="HackerOne: handle do programa (ex: 'acme'). Intigriti: program ID (GUID).",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="HackerOne", value="hackerone"),
        app_commands.Choice(name="Intigriti", value="intigriti"),
    ])
    async def scope_import(
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        handle: str,
    ) -> None:
        settings = bot.settings
        await interaction.response.defer()

        if platform.value == "hackerone":
            if not (settings.hackerone_api_username and settings.hackerone_api_token):
                await interaction.followup.send(
                    embed=error_embed(
                        "Credenciais faltando",
                        "Configure HACKERONE_API_USERNAME e HACKERONE_API_TOKEN no .env.",
                    )
                )
                return
            try:
                items = await h1_fetch_scope(
                    handle, settings.hackerone_api_username, settings.hackerone_api_token
                )
            except HackerOneError as e:
                await interaction.followup.send(embed=error_embed("Erro na API do HackerOne", str(e)))
                return
        else:
            if not settings.intigriti_api_token:
                await interaction.followup.send(
                    embed=error_embed("Credenciais faltando", "Configure INTIGRITI_API_TOKEN no .env.")
                )
                return
            try:
                items = await intigriti_fetch_scope(handle, settings.intigriti_api_token)
            except IntigritiError as e:
                await interaction.followup.send(embed=error_embed("Erro na API do Intigriti", str(e)))
                return

        store = get_scope_store()
        added = 0
        for item in items:
            domain = item.get("domain")
            if not domain:
                continue
            # Always imported as passive — the owner decides mode=active
            # explicitly per target via /scope add, never automatically.
            store.add(
                domain,
                mode="passive",
                rate_limit_rps=5.0,
                notes=f"Importado de {platform.name}/{handle}",
                platform=platform.value,
                program_handle=handle,
                platform_scope_id=item.get("platform_scope_id"),
            )
            added += 1

        await audit_log(
            str(interaction.user.id), "scope:import", target=handle, platform=platform.value, count=added
        )
        await interaction.followup.send(
            embed=ok_embed(
                "Import concluido",
                f"{added} alvo(s) importado(s) de {platform.name}/{handle}, todos como `mode=passive`. "
                f"Use `/scope add` pra ligar scan ativo em algum deles.",
            )
        )

    bot.tree.add_command(group)
