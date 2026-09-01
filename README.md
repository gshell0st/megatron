# megatron

Framework autônomo de bug bounty (recon, exposição de arquivos/endpoints,
checagens leves de XSS/SQLi) controlado inteiramente por um bot em um
servidor Discord privado. Ferramentas fazem o trabalho pesado; Claude Code
(headless) entra só como analista econômico — triagem em lote, não por
ferramenta.

Arquitetura completa: `/home/kali/.claude/plans/stateless-hopping-gizmo.md`.
Regras/invariantes de segurança: `CLAUDE.md`.

## Setup

```bash
cd /home/kali/megatron
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
cp scope.yaml.example scope.yaml   # se ainda nao existir
```

### 1. Criar o bot no Discord

1. https://discord.com/developers/applications -> New Application.
2. Bot -> Reset Token -> copie para `DISCORD_BOT_TOKEN` no `.env`.
3. Bot -> desative "Public Bot" (so voce deve poder convidar).
4. OAuth2 -> URL Generator -> scopes `bot` + `applications.commands`,
   permissions mínimas (Send Messages, Embed Links, Read Message History) ->
   abra a URL gerada e convide o bot para o SEU servidor privado (só voce +
   o bot).
5. Ative "Developer Mode" no Discord (User Settings -> Advanced), clique
   com o botão direito no seu servidor e em voce mesmo para copiar
   `GUILD_ID` e `OWNER_DISCORD_ID` para o `.env`.

### 2. Editar o escopo autorizado

Edite `scope.yaml` (nunca é commitado) com os domínios que você está
realmente autorizado a testar (programas de bug bounty, VDP, etc). Qualquer
alvo fora dessa lista é recusado pelo bot — sem exceção.

### 3. Rodar

```bash
.venv/bin/python megatron initdb          # cria data/megatron.db
.venv/bin/python megatron scope check example.com   # debug do scope gate
.venv/bin/python megatron run             # inicia o bot (primeiro plano)
```

Para rodar 24/7 sem terminal aberto (WSL local):

```bash
scripts/run_dev.sh start     # tmux em background
scripts/run_dev.sh attach    # ver logs ao vivo
scripts/run_dev.sh stop
```

Para algo mais resiliente (restart automático em crash), veja
`scripts/megatron.service` (systemd --user — este WSL já tem systemd
ativo).

## Comandos no Discord

| Comando | O que faz |
|---|---|
| `/scope list\|add\|remove\|reload` | Gerencia `scope.yaml` |
| `/recon target` | Pipeline subfinder -> httpx -> nuclei |
| `/jobs status [job_id]\|cancel job_id` | Acompanha/cancela jobs |
| `/findings target [severity] [status]` | Lista achados |
| `/report target` | 1 chamada Claude, resumo escrito dos achados pendentes |
| `/quota` | Uso diário de invocações do Claude |
| `/system pause\|resume` | Kill switch global |

`/scan` (ffuf/dalfox/sqlmap) é Fase 2, ainda não implementado.

## Como o "cérebro" é usado com economia

Claude nunca vê uma linha crua de ferramenta. Cada job de recon roda até 1
chamada `claude -p` (headless, `--restricted`, sem acesso a arquivos/tools,
schema JSON forçado) só se houver achados relevantes (severidade
medium+ ou tipo "exposure"). Se a quota diária (`MEGATRON_CLAUDE_DAILY_BUDGET`
no `.env`, default 20/dia) estiver esgotada, os achados brutos ficam
disponíveis via `/findings` sem análise, e `/report` pode ser usado depois.

## Desenvolvimento

Ver `CLAUDE.md` para convenções e invariantes de segurança antes de mexer
no código (principalmente o scope gate — nunca contornar).
