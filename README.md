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

### Rodando com Docker

```bash
make          # setup (.env/scope.yaml a partir dos .example) + build + up
make logs     # acompanhar
make shell    # abrir um shell dentro do container
make down     # parar
```

O container reusa a sessão do plano Pro já autenticada no host (monta
`~/.claude` e `~/.claude.json` read-only) — não precisa `claude login` nem
`ANTHROPIC_API_KEY` dentro do container. Se o seu Docker exigir `sudo`
(comum em instalação via snap sem o usuário no grupo `docker`), rode
`sudo usermod -aG docker $USER` e abra um novo shell (ou `newgrp docker`)
antes do `make`.

## Comandos no Discord

| Comando | O que faz |
|---|---|
| `/scope list\|add\|remove\|reload` | Gerencia `scope.yaml` |
| `/scope import platform:hackerone\|intigriti handle:<programa>` | Importa escopo via API oficial do pesquisador (sempre como `mode=passive`) |
| `/recon target` | Pipeline subfinder -> httpx -> nuclei |
| `/scan target type:ffuf\|xss\|sqli [url]` | Scan ativo leve (exige `mode=active` no scope.yaml; xss/sqli exigem `url` com parametro) |
| `/jobs status [job_id]\|cancel job_id` | Acompanha/cancela jobs |
| `/findings target [severity] [status]` | Lista achados |
| `/report target` | 1 chamada Claude, resumo escrito dos achados pendentes |
| `/submit draft target` | Rascunho de report (HackerOne) a partir de achados `reviewed-priority` |
| `/submit confirm draft_id` | Envia de fato pro HackerOne — **nunca automatico**, so nesse comando |
| `/submit list\|discard` | Gerencia rascunhos pendentes |
| `/quota` | Uso diário de invocações do Claude |
| `/system pause\|resume` | Kill switch global |

O heartbeat horário (config `STATUS_CHANNEL_ID` no `.env`) posta uptime,
jobs na fila/rodando e uso de quota do Claude nesse canal automaticamente.
Esse mesmo canal recebe um aviso extra assim que o uso do Claude cruzar 80%
da quota diária — dispara na hora (logo apos a chamada que cruzou) e depois
no maximo 1x a cada 6h enquanto continuar >= 80%, pra nao virar spam.

## Como o "cérebro" é usado com economia

Claude nunca vê uma linha crua de ferramenta. Cada job (recon ou scan ativo)
roda até 1 chamada `claude -p` (headless, `--restricted`, sem acesso a
arquivos/tools, schema JSON forçado) só se houver achados relevantes
(severidade medium+ ou tipo "exposure"). `/report` e `/submit draft` cada um
gastam mais 1 chamada, sob demanda. Se a quota diária
(`MEGATRON_CLAUDE_DAILY_BUDGET` no `.env`, default 20/dia) estiver esgotada,
os achados brutos ficam disponíveis via `/findings` sem análise.

Todo prompt (triagem, report, rascunho de submissão) instrui o modelo a
priorizar **impacto real** acima de severidade bruta ou contagem de
achados — ver `core/claude_bridge/prompts.py`.

## Integração com plataformas (HackerOne / Intigriti)

Confirmado por pesquisa direta nas APIs (não assumido): HackerOne tem
endpoint real de submissão de report por pesquisador
(`POST /v1/hackers/reports`); Intigriti tem API de pesquisador só de
leitura (programas/escopo); Bugcrowd não tem API pública pra nenhum dos
dois lados de pesquisador, por isso fica de fora por enquanto.

- `HACKERONE_API_USERNAME` / `HACKERONE_API_TOKEN` no `.env` habilitam
  `/scope import platform:hackerone` e `/submit`.
- `INTIGRITI_API_TOKEN` habilita `/scope import platform:intigriti` (só
  leitura de escopo — submissão nessa plataforma continua manual, via site).
- `/submit` nunca envia nada sozinho: `/submit draft` só gera e guarda um
  rascunho; a chamada real à API do HackerOne só acontece em
  `/submit confirm`, feito por você depois de revisar o texto.
- HackerOne exige Signal >= 1.0 na conta pra aceitar submissões via API
  (regra deles, não nossa — configure suas credenciais numa conta que já
  atinja isso).

## Desenvolvimento

Ver `CLAUDE.md` para convenções e invariantes de segurança antes de mexer
no código (principalmente o scope gate — nunca contornar).
