# megatron

Framework de bug bounty autônomo, orquestrado 100% via um servidor Discord
privado (bot + dono). Ferramentas (subfinder/httpx/nuclei/ffuf/sqlmap/dalfox/
nmap) fazem o trabalho pesado; Claude é usado só como analista econômico —
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
- Claude é invocado no máximo 1x por job (triagem) e 1x por `/report` —
  nunca por ferramenta, nunca por estágio do pipeline. Ver
  `core/claude_bridge/quota.py`.

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

- Rodar qualquer tool wrapper (subfinder/httpx/nuclei/ffuf/sqlmap/dalfox) contra
  um alvo real dentro de uma sessão de dev sem antes confirmar que é um alvo
  de teste sancionado em `scope.yaml` — mesmo que pareça só um teste do
  wrapper.
- `git commit` incluindo `data/`, `scope.yaml` ou `.env` (todos gitignored,
  nunca forçar `git add -f` neles).

## Estrutura

```
bot/            discord.py — comandos, formatação, client
core/config.py  env vars, MEGATRON_HOME, resolução de paths de tools
core/scope/     scope.yaml loader + validador (o "portão" de segurança)
core/db/        schema.sql + wrapper sqlite3 async
core/tools/     um wrapper por ferramenta (build_command + parse_output)
core/pipelines/ orquestra os wrappers em sequência (recon.py = Fase 1)
core/jobs/      fila asyncio + runner de subprocess + modelos
core/claude_bridge/  invocação headless do Claude (quota, prompts, invoke)
core/findings/  dedup por hash + filtro de severidade pra triagem
data/           gitignored — runtime (DB, logs, saída bruta das tools)
```
