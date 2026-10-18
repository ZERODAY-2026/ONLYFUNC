"""Schema catalog: Snowflake se live table/column names, aur unke saath datasets.yaml ke meanings, joins, metrics aur
examples, taaki prompts hamesha asli schema aur business definitions se match karein."""
import json

from . import trace
from .config import Config
from .snowflake_client import run_query


def discover_tables(conn, cfg: Config) -> None:
    """Har `tables: auto` dataset ki tables wahi bharta hai jo connected role apne schema me dekh sakta hai.
    Jo tables usi schema ke kisi dusre dataset me already listed hain woh us dataset ke paas hi rehti hain (uske meanings,
    metrics aur joins bache rehte hain). Dobara call karna safe hai: list phir se banti hai, toh nayi tables aa jaati hain aur hataayi gayi gayab ho jaati hain."""
    for d in cfg.datasets:
        if not d.auto:
            continue
        claimed = {t.upper() for o in cfg.datasets if not o.auto and (o.database.upper(), o.schema.upper()) == (d.database.upper(), d.schema.upper()) for t in o.tables}
        res = run_query(conn, f"""
            SELECT table_name FROM {d.database}.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{d.schema.upper()}' AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name""")
        d.tables = [r[0] for r in res.rows if r[0].upper() not in claimed]
        trace.emit("SCHEMA", f"auto dataset {d.name}: {len(res.rows)} tables visible in {d.database}.{d.schema}, {len(d.tables)} unclaimed -> {d.tables}")


def describe_schema(conn, cfg: Config) -> str:
    discover_tables(conn, cfg)
    lines = []
    for d in cfg.datasets:
        if not d.tables:
            continue  # auto dataset ko abhi kuch naya nahi mila
        lines.append(f"-- Dataset '{d.name}': {d.description}")
        if d.scope:
            lines.append(f"Scope: {d.scope}")
        if d.auto:
            lines.append("These tables were discovered automatically: no meanings, joins or metrics are declared. Join only on columns with the same name and meaning, and state your assumptions.")
        res = run_query(conn, f"""
            SELECT c.table_name, c.column_name, c.data_type, t.row_count
            FROM {d.database}.INFORMATION_SCHEMA.COLUMNS c
            JOIN {d.database}.INFORMATION_SCHEMA.TABLES t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = '{d.schema.upper()}'
              AND c.table_name IN ({", ".join(repr(t.upper()) for t in d.tables)})
            ORDER BY c.table_name, c.ordinal_position""")
        tables: dict[str, list[str]] = {}
        row_counts: dict[str, int | None] = {}
        for table, column, dtype, row_count in res.rows:
            meaning = d.columns.get(table, {}).get(column)
            tables.setdefault(table, []).append(f"{column} {dtype}" + (f" [{meaning}]" if meaning else ""))
            row_counts[table] = row_count
        for table, cols in tables.items():
            live = f" [live row count from Snowflake: {int(row_counts[table]):,}]" if row_counts.get(table) is not None else ""
            note = (f"  -- {d.notes[table]}" if table in d.notes else "") + live
            lines.append(f"{d.database}.{d.schema}.{table}({', '.join(cols)}){note}")
        if d.joins:
            lines.append("Allowed joins (use only these): " + "; ".join(d.joins))
        if d.metrics:
            lines.append("Metric definitions (follow exactly): " + "; ".join(f"{k}: {v}" for k, v in d.metrics.items()))
    return "\n".join(lines)


def describe_examples(cfg: Config) -> str:
    """datasets.yaml ke few-shot examples, un JSON replies ki shakal me jo model ko deni hain."""
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


def dataset_status(conn, cfg: Config) -> dict[str, dict]:
    """Har dataset ke liye Snowflake se live pooch kar batata hai ki uski kitni configured tables sach me dikhti hain, aur har table me
    kitne columns aur (metadata se) kitni rows hain. Ek query har database par.
    Return: {dataset: {"present": n, "total": m, "missing": [...], "tables": {TABLE: {"rows": int | None, "columns": int}}}}."""
    seen: dict[str, dict[str, dict[str, tuple]]] = {}
    for d in cfg.datasets:
        db = d.database.upper()
        if db not in seen:
            res = run_query(conn, f"""
                SELECT t.table_schema, t.table_name, t.row_count, COUNT(c.column_name)
                FROM {d.database}.INFORMATION_SCHEMA.TABLES t
                LEFT JOIN {d.database}.INFORMATION_SCHEMA.COLUMNS c
                  ON c.table_schema = t.table_schema AND c.table_name = t.table_name
                WHERE t.table_schema <> 'INFORMATION_SCHEMA'
                GROUP BY t.table_schema, t.table_name, t.row_count""")
            by_schema: dict[str, dict[str, tuple]] = {}
            for schema, table, rows, columns in res.rows:
                by_schema.setdefault(schema.upper(), {})[table.upper()] = (None if rows is None else int(rows), int(columns))
            seen[db] = by_schema
    out = {}
    for d in cfg.datasets:
        present = seen[d.database.upper()].get(d.schema.upper(), {})
        missing = [t for t in d.tables if t.upper() not in present]
        out[d.name] = {"present": len(d.tables) - len(missing), "total": len(d.tables), "missing": missing,
                       "tables": {t.upper(): {"rows": present[t.upper()][0], "columns": present[t.upper()][1]}
                                  for t in d.tables if t.upper() in present}}
    return out


def missing_tables(conn, cfg: Config) -> list[str]:
    """Configured tables jo current role ko nahi dikhti (ya toh abhi load nahi hui, ya grant nahi hai)."""
    missing = []
    for d in cfg.datasets:
        res = run_query(conn, f"""
            SELECT table_name FROM {d.database}.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{d.schema.upper()}'""")
        present = {r[0].upper() for r in res.rows}
        missing += [f"{d.database}.{d.schema}.{t}" for t in d.tables if t.upper() not in present]
    return missing
