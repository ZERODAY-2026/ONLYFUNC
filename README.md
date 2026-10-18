# ONLYFUNC-: the Snowflake layer of DataMind

Only the Snowflake side of the project: login, running SQL, schema checks, dataset loading, key setup and the SQL setup script. No AI model and no UI. The AI layer hands this layer **validated SQL** and gets back rows, columns and a Snowflake query ID.

## The one thing to call

```python
from datamind.executor import make_executor

executor = make_executor()                  # logs in lazily with the read-only role
result = executor("SELECT COUNT(*) AS N FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS")
# {"rows": [{"N": 1500000}], "columns": ["N"], "query_id": "01c7...", "truncated": False}
executor.close()                            # or: with make_executor() as executor: ...
```

This is exactly the shape the teammate's AI package expects: `agent.ask(question, executor)`.

| Behaviour | Detail |
|---|---|
| Read-only | Only `SELECT` / `WITH` run. The app also logs in as the read-only role `DM_READER`. |
| SQL errors | Raised unchanged (`snowflake.connector.errors.ProgrammingError`) so the AI layer can repair its SQL. |
| Lost session | An expired token or dropped connection is re-opened once and the query retried. A second failure is raised. |
| Result cap | `max_rows` (default 1000); `truncated` is `True` if there was more. |
| Statement timeout | 60 s per statement (`DM_STATEMENT_TIMEOUT`), so a runaway query cannot burn trial credits. |
| Duplicate column names | Get `_2`, `_3` suffixes instead of silently overwriting each other in the row dicts. |

## Quick start (Windows)
`run.bat` is the one way to run things. It creates `.venv`, installs the pinned packages, creates `.env`, checks Snowflake and loads missing datasets.
`run.bat check` (default) | `run.bat live` | `run.bat load` | `run.bat keygen` | `run.bat test` | `run.bat repair` | `run.bat help`

## Setup (step by step)

1. **Snowflake account:** trial account at signup.snowflake.com. In Snowsight run `setup.sql` as ACCOUNTADMIN (Run all). It creates the warehouse `DM_WH`, database `DATAMIND`, and roles `DM_READER` (read-only) and `DM_LOADER`.
2. **Python:** `python -m venv .venv`, activate it, `pip install -r requirements.txt`.
3. **Credentials:** copy `.env.example` to `.env`; set `SNOWFLAKE_ACCOUNT` (from your Snowsight URL) and `SNOWFLAKE_USER`.
   For key-pair login (recommended): `python -m datamind.keys` creates the key (kept in `.keys/`, never commit it), fills the path in `.env`, and prints one SQL block to run in Snowsight. Then set `SNOWFLAKE_USER=DM_APP`.
4. **Check:** `python -m datamind.preflight` (exit 0 = ready, 2 = the extra dataset is not loaded yet, 1 = a problem with the lines marked `[FAIL]`).
5. **Load the extra dataset** (UCI Wine Quality, CC BY 4.0): `python load_data.py`.
6. **Prove it works:** `python live_check.py`, then `python -m pytest -q`.

## Files

| File | Job |
|---|---|
| `datamind/executor.py` | The callable above. |
| `datamind/snowflake_client.py` | `connect()` (key pair, token or password) and `run_query()`. |
| `datamind/catalog.py` | Reads live table and column names; lists configured tables that are missing. |
| `datamind/config.py`, `datasets.yaml` | Which databases, schemas and tables exist; how to load extras. |
| `datamind/keys.py` | Key-pair setup helper. |
| `datamind/preflight.py` | Readiness checks. |
| `datamind/logs.py` | Writes tracebacks to `logs/datamind.log` (users see clean messages). |
| `load_data.py`, `setup.sql` | Dataset loader and the one-time account setup. |
| `live_check.py`, `tests/` | Live check against the real account; offline tests with a fake connection. |

## Rules for this layer
- Secrets only in `.env` and `.keys/` (both gitignored). Never paste tokens or keys into chat or commits.
- The reader role must stay read-only; never run the app as ACCOUNTADMIN.
- `datasets.yaml` lists the allowed tables; add datasets there, not in code. Source: Snowflake sample data (referenced in place, no open licence stated) and UCI Wine Quality (CC BY 4.0).

MIT licence (see `LICENSE`).
