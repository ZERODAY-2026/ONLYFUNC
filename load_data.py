"""Loads datasets that have a `load:` block in datasets.yaml into Snowflake (run once, uses the loader role)."""
from snowflake.connector.pandas_tools import write_pandas
from ucimlrepo import fetch_ucirepo

from datamind.config import load_config
from datamind.snowflake_client import connect


def main():
    cfg = load_config()
    conn = connect("SNOWFLAKE_LOADER_ROLE")
    for d in cfg.datasets:
        spec = d.load
        if not spec:
            continue
        if spec["type"] != "uci":
            raise SystemExit(f"Unsupported load type: {spec['type']}")
        df = fetch_ucirepo(id=spec["uci_id"]).data.original
        df.columns = [c.upper().replace(" ", "_") for c in df.columns]
        ok, _, nrows, _ = write_pandas(
            conn, df, spec["table"], database=d.database, schema=d.schema,
            auto_create_table=True, overwrite=True)
        print(f"{d.name}: loaded {nrows} rows into {d.database}.{d.schema}.{spec['table']} (ok={ok})")
    conn.close()


if __name__ == "__main__":
    main()
