"""Schema catalog: live table/column names from Snowflake, enriched with the meanings, joins, metrics and
examples declared in datasets.yaml, so prompts always match reality and the business definitions."""
import json

from .config import Config
from .snowflake_client import run_query


def discover_tables(conn, cfg: Config) -> None:
    """Fills in the tables of every `tables: auto` dataset from what the connected role can see in its schema.
    Tables that another dataset in the same schema already lists are left to that dataset (it keeps its meanings,
    metrics and joins). Safe to call again: it recomputes the list, so new tables appear and dropped ones vanish."""
    for d in cfg.datasets:
        if not d.auto:
            continue
        claimed = {t.upper() for o in cfg.datasets if not o.auto and (o.database.upper(), o.schema.upper()) == (d.database.upper(), d.schema.upper()) for t in o.tables}
        res = run_query(conn, f"""
            SELECT table_name FROM {d.database}.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{d.schema.upper()}' AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name""")
        d.tables = [r[0] for r in res.rows if r[0].upper() not in claimed]


def describe_schema(conn, cfg: Config) -> str:
    discover_tables(conn, cfg)
    lines = []
    for d in cfg.datasets:
        if not d.tables:
            continue  # an auto dataset that currently finds nothing new
        lines.append(f"-- Dataset '{d.name}': {d.description}")
        if d.scope:
            lines.append(f"Scope: {d.scope}")
        if d.auto:
            lines.append("These tables were discovered automatically: no meanings, joins or metrics are declared. Join only on columns with the same name and meaning, and state your assumptions.")
        res = run_query(conn, f"""
            SELECT table_name, column_name, data_type
            FROM {d.database}.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema = '{d.schema.upper()}'
              AND table_name IN ({", ".join(repr(t.upper()) for t in d.tables)})
            ORDER BY table_name, ordinal_position""")
        tables: dict[str, list[str]] = {}
        for table, column, dtype in res.rows:
            meaning = d.columns.get(table, {}).get(column)
            tables.setdefault(table, []).append(f"{column} {dtype}" + (f" [{meaning}]" if meaning else ""))
        for table, cols in tables.items():
            note = f"  -- {d.notes[table]}" if table in d.notes else ""
            lines.append(f"{d.database}.{d.schema}.{table}({', '.join(cols)}){note}")
        if d.joins:
            lines.append("Allowed joins (use only these): " + "; ".join(d.joins))
        if d.metrics:
            lines.append("Metric definitions (follow exactly): " + "; ".join(f"{k}: {v}" for k, v in d.metrics.items()))
    return "\n".join(lines)


def describe_examples(cfg: Config) -> str:
    """Few-shot examples from datasets.yaml, rendered as the JSON replies the model must produce."""
    out = []
    for d in cfg.datasets:
        for ex in d.examples:
            if "sql" in ex:
                reply = {"action": "query", "sql": ex["sql"], "assumptions": ex.get("assumptions", []), "message": ""}
            elif "clarify" in ex:
                reply = {"action": "clarify", "sql": "", "assumptions": [], "message": ex["clarify"]}
            else:
                reply = {"action": "unsupported", "sql": "", "assumptions": [], "message": ex.get("unsupported", "")}
            out.append(f"Q: {ex['question']}\nA: {json.dumps(reply)}")
    return "\n".join(out)


def missing_tables(conn, cfg: Config) -> list[str]:
    """Configured tables the current role cannot see (not loaded yet, or no grant)."""
    missing = []
    for d in cfg.datasets:
        res = run_query(conn, f"""
            SELECT table_name FROM {d.database}.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{d.schema.upper()}'""")
        present = {r[0].upper() for r in res.rows}
        missing += [f"{d.database}.{d.schema}.{t}" for t in d.tables if t.upper() not in present]
    return missing
