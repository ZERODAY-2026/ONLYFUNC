# DataMind: talk to your data

Ask questions in plain language. **Gemma** (via Ollama) translates the question into SQL, a read-only validator checks it, **Snowflake** runs it on the real data, and Gemma explains only the rows that came back. Every answer shows the executed SQL, the rows and the Snowflake query ID.

Five datasets are configured: Snowflake's TPC-H sample, UCI Wine Quality, UCI Bank Marketing, UCI Student Performance and three Our World in Data indicators (see Datasets and licences).

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
| `config.py`, `datasets.yaml` | Which datasets exist (an explicit table list, or `tables: auto`). Add a dataset here, not in code. |
| `preflight.py` | Readiness checks (settings, Snowflake, datasets, Gemma). |
| `keys.py`, `ports.py`, `cli.py` | Key-pair setup, free port, ask-from-terminal. One job each. |
| `run.bat` | Self-healing launcher. |
| `eval/` | Live checks: `smoke` (routing) and the ground-truth evaluation. |
| `app.py`, `load_data.py` | Streamlit UI and dataset loader (`uci` and `csv` recipes). |
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
Add an entry to `datasets.yaml` (database, schema, tables, optional `load:` recipe). No code changes. A `load:` recipe is `type: uci` (with `uci_id`) or `type: csv` (with `url`), plus `table` and an optional `rename:`; give a list of recipes for a dataset with several tables. `run.bat load` (or `python load_data.py`) loads them into your Snowflake account and overwrites existing tables.

**Automatic tables (optional):** `tables: auto` lets Snowflake decide which tables a dataset has. Add an entry such as `{name: extras, database: UCI, schema: PUBLIC, tables: auto}` and it picks up any table or view in that schema that the read-only role can see, minus tables another dataset already lists, at startup or when you press **Re-scan tables** in the sidebar. Discovered tables get live column names and types but no meanings, joins or metrics, so answers about them are less reliable until you declare those in `datasets.yaml`. No dataset uses it in the shipped config, because every table is listed explicitly.

## Guardrails
Single statement only, no writes or DDL, only tables listed in `datasets.yaml`, fully qualified names, automatic `LIMIT`, and the app logs in as the read-only-by-default `DM_READER` role.

## Privacy note
With Ollama cloud, the question and up to 50 result rows are sent to Ollama's servers for the explanation step. Use a local Ollama model to keep everything on your machine.

## Datasets and licences
Each source has its own place in Snowflake:

| Snowflake database | Dataset | Tables | Source and licence |
|---|---|---|---|
| `SNOWFLAKE_SAMPLE_DATA` (`TPCH_SF1`) | `tpch` | 8 TPC-H tables | Snowflake sample data, referenced in place and not copied here. No open licence stated. |
| `SNOWFLAKE_SAMPLE_DATA` (`TPCDS_SF10TCL`) | `tpcds` | 12 TPC-DS tables (`STORE_SALES` has 28.8 billion rows) | Snowflake sample data, referenced in place. No open licence stated. |
| `UCI` (`PUBLIC`) | `wine_quality` | `WINE_QUALITY` (6,497 rows) | UCI Wine Quality (id 186), CC BY 4.0. |
| `UCI` (`PUBLIC`) | `bank_marketing` | `BANK_MARKETING` (45,211 rows) | UCI Bank Marketing (id 222), CC BY 4.0. |
| `UCI` (`PUBLIC`) | `student_performance` | `STUDENT_PERFORMANCE` (649 rows) | UCI Student Performance (id 320), CC BY 4.0. |
| `OWID` (`PUBLIC`) | `owid` | `LIFE_EXPECTANCY`, `GDP_PER_CAPITA`, `POPULATION` | Our World in Data (life expectancy, GDP per capita, population with UN projections), CC BY 4.0 for the processed data. Underlying sources: Riley (2005), Zijdeman et al. (2015), HMD (2025), UN WPP (2024); Eurostat, OECD, IMF and World Bank (2026). Attribute Our World in Data and the original sources. |

`setup.sql` creates the `UCI` and `OWID` databases and the roles. `load_data.py` downloads the UCI and Our World in Data files into them at load time. No dataset files are stored in this repo.

**TPC-DS and credits:** TPC-DS queries scan very large tables, so a TPC-DS question can take from seconds to a few minutes on an XSMALL warehouse and uses more trial credit than the other datasets. The catalogue tells Gemma to filter by year first, and `DM_STATEMENT_TIMEOUT` is 300 seconds in `.env.example` (the code default is 60).

## Credits
The semantic catalogue idea, number-grounding check, function/join allowlists and the first seven routing cases are adapted from the team's AI-module handoff package (MIT).

## Known limitations
Answer accuracy depends on the Gemma model. Verified so far: 93 unit tests, 9/9 live routing cases (`run.bat smoke`), and the 66-case ground-truth evaluation (`run.bat eval`).

**Evaluation (Gemma 4 31B, 2026-10-18):** the first run on the original TPC-H and wine questions scored **45/47 (96%)** with no tuning (`eval/results/run1_before_fixes.md`). It exposed one real agent mistake (grouping parts by a non-unique name, fixed with a general prompt rule) and one over-specified truth case (corrected). After the fixes it scored 47/47. We then added Our World in Data, Bank Marketing and Student Performance with 19 more cases; they all passed on the first run. The full 66-case set scored **66/66** (`eval/results/latest.md`).

Two more things the extra datasets exposed, both fixed and kept honest here:
- A question that compares two years with aliased CTEs ("which 5 countries gained the most life expectancy between 1990 and 2020, and what was their GDP per capita") was wrongly refused by the validator. That was a validator bug, fixed and covered by a unit test and eval case `o09`.
- One full run failed `c05` (the model wrote `'Germany'` where TPC-H stores `GERMANY`) and then passed 3 of 3 reruns. We documented the uppercase naming in `datasets.yaml`; the next full run passed. Expect occasional model variation.

Treat 96% on the first, untuned run as the fair estimate: the final 100% comes after fixing what the set revealed, and the set is small. The questions are not used as prompt examples. Judges' unseen questions may behave differently. Metric definitions in `datasets.yaml` are followed literally; keep them accurate.
