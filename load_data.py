"""Jin datasets me datasets.yaml ka `load:` block hai unko Snowflake me load karta hai (ek baar chalao, loader role use hota hai).

Har source ka apna database hai (database aur schema datasets.yaml ke har dataset se aate hain, jaise UCI.PUBLIC aur
OWID.PUBLIC). setup.sql databases banata hai aur PUBLIC schema ka owner DM_LOADER ko banata hai; yeh script phir
read-only role ko USAGE deti hai aur har load ke baad SELECT.

`load:` ya toh ek recipe hota hai ya recipes ki list (har table ke liye ek). Recipe ke types:
  uci   uci_id, table, optional rename {OLD: NEW}   (UCI Machine Learning Repository, ucimlrepo se)
  csv   url, table, optional rename {OLD: NEW}      (koi bhi public CSV, jaise Our World in Data ka indicator)
"""
import os

import pandas as pd
from snowflake.connector.pandas_tools import write_pandas
from ucimlrepo import fetch_ucirepo

from datamind import trace
from datamind.config import load_config
from datamind.snowflake_client import connect, run_query


def fetch(spec: dict) -> pd.DataFrame:
    source = f"UCI dataset id {spec['uci_id']}" if spec["type"] == "uci" else str(spec.get("url"))
    with trace.span("DOWNLOAD", f"{spec['type']} {source}") as info:
        if spec["type"] == "uci":
            df = fetch_ucirepo(id=spec["uci_id"]).data.original
        elif spec["type"] == "csv":
            df = pd.read_csv(spec["url"])
        else:
            raise SystemExit(f"Unsupported load type: {spec['type']}")
        info.update(rows=len(df), columns=len(df.columns), memory_bytes=int(df.memory_usage(deep=True).sum()))
    df.columns = [c.upper().replace(" ", "_") for c in df.columns]
    return df.rename(columns={k.upper(): v.upper() for k, v in (spec.get("rename") or {}).items()})


def recipes(load) -> list[dict]:
    return load if isinstance(load, list) else [load]


def prepare_schema(conn, database: str, schema: str, reader: str) -> None:
    """Source schema agar nahi hai toh bana deta hai aur read-only role ko use karne deta hai. Uski tables load ke baad grant hoti hain."""
    target = f"{database}.{schema}"
    run_query(conn, f"CREATE SCHEMA IF NOT EXISTS {target}")
    run_query(conn, f"GRANT USAGE ON SCHEMA {target} TO ROLE {reader}")


def main():
    cfg = load_config()
    reader = os.getenv("SNOWFLAKE_READER_ROLE", "DM_READER")
    conn = connect("SNOWFLAKE_LOADER_ROLE")
    for d in cfg.datasets:
        if not d.load:
            continue
        prepare_schema(conn, d.database, d.schema, reader)
        for spec in recipes(d.load):
            df = fetch(spec)
            with trace.span("LOAD", f"write_pandas {len(df)} rows x {len(df.columns)} columns into {d.database}.{d.schema}.{spec['table']} (overwrite)") as info:
                ok, _, nrows, _ = write_pandas(
                    conn, df, spec["table"], database=d.database, schema=d.schema,
                    auto_create_table=True, overwrite=True)
                info.update(rows_loaded=nrows, ok=ok)
            print(f"{d.name}: loaded {nrows} rows into {d.database}.{d.schema}.{spec['table']} (ok={ok})")
        run_query(conn, f"GRANT SELECT ON ALL TABLES IN SCHEMA {d.database}.{d.schema} TO ROLE {reader}")
    conn.close()


if __name__ == "__main__":
    main()
