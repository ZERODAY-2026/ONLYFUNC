# DataMind: talk to your data

Ask questions in plain language. **Gemma** (via Ollama) translates the question into SQL, a read-only validator checks it, **Snowflake** runs it on the real data, and Gemma explains only the rows that came back. Every answer shows the executed SQL, the rows and the Snowflake query ID.

```
question -> Gemma (SQL) -> validator (SELECT only, allowlisted tables, LIMIT) -> Snowflake -> rows -> Gemma (explanation) -> UI
```

## Quick start (Windows)
1. **Snowflake:** create a trial account (signup.snowflake.com). In Snowsight, run `setup.sql` as ACCOUNTADMIN (Run all).
2. **Credentials:** `run.bat keygen` creates a key pair and prints one SQL block to run in Snowsight; it also sets the key path in `.env`. Set `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_USER=DM_APP` in `.env`.
3. **Gemma:** put an Ollama API key in `.env` as `OLLAMA_API_KEY` (https://ollama.com/settings/keys), or run Ollama locally (see `.env.example`).
4. **Run:** `run.bat`. It creates `.venv`, installs packages, loads missing datasets, checks everything and opens the app.

`run.bat help` lists the commands: `check`, `ask "question"`, `load`, `live`, `smoke`, `eval`, `keygen`, `test`, `repair`.

## Modules (one job each)
| Module | Job |
|---|---|
| `llm.py`, `prompts.py` | Gemma calls and prompt text. No data access. |
| `snowflake_client.py` | Login and running SQL. The only data access. |
| `executor.py` | Snowflake executor callable for other AI layers (read-only, session retry, row cap). |
| `catalog.py` | Live table/column names plus the meanings, joins, metrics and examples from `datasets.yaml`. |
| `validator.py` | Read-only SQL guardrail: one SELECT, allowlisted tables, functions and joins, automatic LIMIT. |
| `grounding.py` | Checks that numbers in the explanation really appear in the result rows. |
| `agent.py`, `models.py` | The workflow and its result type. |
| `config.py`, `datasets.yaml` | Which datasets exist. Add a dataset here, not in code. |
| `preflight.py` | Readiness checks (settings, Snowflake, datasets, Gemma). |
| `keys.py`, `ports.py`, `cli.py` | Key-pair setup, free port, ask-from-terminal. One job each. |
| `run.bat` | Self-healing launcher. |
| `eval/` | Live checks: `smoke` (routing) and the ground-truth evaluation. |
| `app.py`, `load_data.py` | Streamlit UI and dataset loader. |
| `live_check.py` | Proves the Snowflake layer works against the real account (`run.bat live`). |

## Snowflake executor (for other AI layers)

```python
from datamind.executor import make_executor

executor = make_executor()                  # logs in lazily with the read-only role
result = executor("SELECT COUNT(*) AS N FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS")
# {"rows": [{"N": 1500000}], "columns": ["N"], "query_id": "01c7...", "truncated": False}
executor.close()                            # or: with make_executor() as executor: ...
```

| Behaviour | Detail |
|---|---|
| Read-only | Only `SELECT` / `WITH` run. The app also logs in as the read-only role `DM_READER`. |
| SQL errors | Raised unchanged (`snowflake.connector.errors.ProgrammingError`) so the AI layer can repair its SQL. |
| Lost session | An expired token or dropped connection is re-opened once and the query retried. A second failure is raised. |
| Result cap | `max_rows` (default 1000); `truncated` is `True` if there was more. |
| Statement timeout | 60 s per statement (`DM_STATEMENT_TIMEOUT`), so a runaway query cannot burn trial credits. |
| Duplicate column names | Get `_2`, `_3` suffixes instead of silently overwriting each other in the row dicts. |

## Adding a dataset
Add an entry to `datasets.yaml` (database, schema, tables, optional `load:` recipe). No code changes. For better answers also add the optional catalogue: `metrics`, `joins`, `columns`, `notes` and `examples`. Config alone does not prove accuracy: a new dataset still needs its own evaluation questions.

## Guardrails
Single statement only, no writes or DDL, only tables listed in `datasets.yaml`, fully qualified names, automatic `LIMIT`, and the app logs in as the read-only-by-default `DM_READER` role.

## Privacy note
With Ollama cloud, the question and up to 50 result rows are sent to Ollama's servers for the explanation step. Use a local Ollama model to keep everything on your machine.

## Datasets and licences
- Snowflake `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1`: referenced in place, not copied here.
- UCI Wine Quality (id 186): CC BY 4.0, loaded into your own Snowflake account by `load_data.py`.

## Credits
The semantic catalogue idea, number-grounding check, function/join allowlists and the first seven routing cases are adapted from the team's AI-module handoff package (MIT).

## Known limitations
Answer accuracy depends on the Gemma model. Verified so far: 85 unit tests, 9/9 live routing cases (`run.bat smoke`), and the 47-case ground-truth evaluation (`run.bat eval`).

**Evaluation (Gemma 4 31B, 2026-10-18):** the first run scored **45/47 (96%)** with no tuning (`eval/results/run1_before_fixes.md`). It exposed one real agent mistake (grouping parts by a non-unique name, fixed with a general prompt rule) and one over-specified truth case (corrected). After those fixes the rerun scored **47/47** (`eval/results/latest.md`). Treat 96% as the fair estimate: the final 100% comes after fixing what the set revealed, and the set is small. The questions are not used as prompt examples. Judges' unseen questions may behave differently. Metric definitions in `datasets.yaml` are followed literally; keep them accurate.
