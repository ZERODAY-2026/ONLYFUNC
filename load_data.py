"""Loads datasets that have a `load:` block in datasets.yaml into Snowflake (run once, uses the loader role).

`load:` is one recipe or a list of recipes (one per table). Recipe types:
  uci   uci_id, table, optional rename {OLD: NEW}   (UCI Machine Learning Repository via ucimlrepo)
  csv   url, table, optional rename {OLD: NEW}      (any public CSV, for example an Our World in Data indicator)
"""
import pandas as pd
from snowflake.connector.pandas_tools import write_pandas
from ucimlrepo import fetch_ucirepo

from datamind.config import load_config
from datamind.snowflake_client import connect


def fetch(spec: dict) -> pd.DataFrame:
    if spec["type"] == "uci":
        df = fetch_ucirepo(id=spec["uci_id"]).data.original
    elif spec["type"] == "csv":
        df = pd.read_csv(spec["url"])
    else:
        raise SystemExit(f"Unsupported load type: {spec['type']}")
    df.columns = [c.upper().replace(" ", "_") for c in df.columns]
    return df.rename(columns={k.upper(): v.upper() for k, v in (spec.get("rename") or {}).items()})


def recipes(load) -> list[dict]:
    return load if isinstance(load, list) else [load]


def main():
    cfg = load_config()
    conn = connect("SNOWFLAKE_LOADER_ROLE")
    for d in cfg.datasets:
        for spec in recipes(d.load) if d.load else []:
            ok, _, nrows, _ = write_pandas(
                conn, fetch(spec), spec["table"], database=d.database, schema=d.schema,
                auto_create_table=True, overwrite=True)
            print(f"{d.name}: loaded {nrows} rows into {d.database}.{d.schema}.{spec['table']} (ok={ok})")
    conn.close()


if __name__ == "__main__":
    main()
