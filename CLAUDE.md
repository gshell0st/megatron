# megatron

Framework de bug bounty autônomo, orquestrado 100% via um servidor Discord
privado (bot + dono). Ferramentas (subfinder/httpx/nuclei/ffuf/sqlmap/dalfox/
nmap/git-dumper/sslyze/katana) fazem o trabalho pesado; Claude é usado só
como analista econômico —
veja `/home/kali/.claude/plans/stateless-hopping-gizmo.md` para a
arquitetura completa (schema, contrato de invocação do Claude, comandos).

## Invariantes que nunca podem ser violadas

- Todo código que vai tocar um alvo real chama `core.scope.require_scope()`
  (ou `is_in_scope()`) **primeiro**. Nunca cachear o resultado entre
  chamadas, nunca confiar em um valor que não veio dessa checagem agora.
- `/scan` (Fase 2) sempre revalida `mode=active` no `scope.yaml` — nunca
  confiar em um valor lido antes.
- Chamadas headless `claude -p` (em `core/claude_bridge/invoke.py`) nunca
  ganham acesso a tools/arquivos do projeto: sempre `--restricted
  --setting-sources ""`. O "system prompt" delas vive em
  `core/claude_bridge/prompts.py`, versionado como código — não usar este
  CLAUDE.md pra isso.
- O check owner-only em `bot/client.py` (`OwnerOnlyTree.interaction_check`)
  nunca pode ser enfraquecido ou contornado.
- Claude é invocado no máximo 1x por job (triagem), 1x por `/report` e 1x por
  `/submit draft` — nunca por ferramenta, nunca por estágio do pipeline. Ver
  `core/claude_bridge/quota.py`.
- Prompts (`core/claude_bridge/prompts.py`) sempre priorizam **impacto real**
  acima de severidade bruta/contagem de achados — não remover essa framing
  ao editar os prompts.
- `/submit confirm` é o único lugar que chama
  `core.platforms.hackerone.submit_report()` (envio real). `/submit draft`
  nunca envia nada — só gera e guarda um rascunho em `report_drafts`. Nunca
  criar um caminho que pule essa confirmação manual.
- `/scope import` (HackerOne/Intigriti) sempre grava os alvos importados como
  `mode=passive`, nunca `active` — ligar scan ativo é decisão manual do dono
  via `/scope add`.
- `core/tools/git_dumper.py` (dump de repositório `.git` exposto) só pode ser
  chamado depois que `core/checks/webcheck.py` **confirma** a exposição pelo
  corpo da resposta (não só status 200) — `core/pipelines/webcheck.py` é o
  único lugar que decide isso, e nunca roda o dump "no escuro" contra um
  path que só pareceu existir.
- Achados de `core/checks/webcheck.py` só usam `finding_type='exposure'`
  (o que bypassa o filtro de severidade em
  `core/findings/severity.get_triage_candidates()`) quando o corpo da
  resposta foi de fato inspecionado e parece sensível — não adicionar novas
  categorias que marquem `exposure` só por um path ter respondido 200.

## Convenções

- Python 3.12, type hints em tudo, I/O sempre async (nunca sqlite3/subprocess
  bloqueante direto no event loop — usar `asyncio.to_thread` ou subprocess
  assíncrono nativo, como em `core/db/database.py` e `core/jobs/runner.py`).
- Sem comentários explicando o óbvio; só quando há um motivo não-óbvio.
- Rodar via `.venv/bin/python megatron <comando>` (venv do projeto).

## Comandos seguros para rodar sem perguntar

- `.venv/bin/python -m core.db.database` (idempotente, só cria/migra o schema)
- `.venv/bin/python megatron scope check <target>` (só leitura)
- Leitura de `data/*.db`, `data/logs/*`
- `pytest` (quando houver testes)

## Nunca fazer sem confirmar

- Rodar qualquer tool wrapper (subfinder/httpx/nuclei/ffuf/sqlmap/dalfox/
  webcheck/git-dumper/sslyze/katana) contra um alvo real dentro de uma sessão
  de dev sem antes confirmar que é um alvo de teste sancionado em
  `scope.yaml` — mesmo que pareça só um teste do wrapper. Pra validar lógica
  de parsing/detecção sem tocar um alvo real, use um servidor local
  (`aiohttp.web`/`http.server`) como fixture, como foi feito ao construir
  `core/checks/webcheck.py`/`core/tools/tls_scan.py`.
- `git commit` incluindo `data/`, `scope.yaml` ou `.env` (todos gitignored,
  nunca forçar `git add -f` neles).

## Estrutura

```
bot/            discord.py — comandos, formatação, client
core/config.py  env vars, MEGATRON_HOME, resolução de paths de tools
core/scope/     scope.yaml loader + validador (o "portão" de segurança)
core/db/        schema.sql + wrapper sqlite3 async
core/tools/     um wrapper por ferramenta (build_command + parse_output)
core/checks/    checks HTTP em processo, sem subprocess (webcheck.py,
                secrets.py) — usados pelo pipeline webcheck
core/pipelines/ orquestra os wrappers em sequência (recon.py = Fase 1,
                webcheck.py = higiene web em 11 categorias)
core/jobs/      fila asyncio + runner de subprocess + modelos
core/claude_bridge/  invocação headless do Claude (quota, prompts, invoke)
core/findings/  dedup por hash + filtro de severidade pra triagem
core/backlog/   snapshot por alvo em data/backlog/, diff ("beyond compare")
                entre testes, contexto tipo-RAG (precedentes de triagem do
                próprio alvo) injetado na chamada de triagem
core/platforms/ clientes de API do HackerOne (leitura+submit) e Intigriti (só leitura)
data/           gitignored — runtime (DB, logs, saída bruta das tools, backlog/)
```
