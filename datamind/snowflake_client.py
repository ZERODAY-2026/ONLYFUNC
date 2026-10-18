"""All data access goes through Snowflake. Nothing is answered from local files."""
import os
from dataclasses import dataclass

import snowflake.connector

from .config import env


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    query_id: str


def connect(role_var: str = "SNOWFLAKE_READER_ROLE"):
    kwargs = dict(
        account=env("SNOWFLAKE_ACCOUNT"),
        user=env("SNOWFLAKE_USER"),
        warehouse=env("SNOWFLAKE_WAREHOUSE", "DM_WH"),
        role=env(role_var),
    )
    key_file = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")  # key-pair login: no password, token or network policy
    pat = os.getenv("SNOWFLAKE_PAT")  # programmatic access token
    if key_file:
        kwargs["private_key_file"] = key_file
    elif pat:
        kwargs.update(authenticator="PROGRAMMATIC_ACCESS_TOKEN", token=pat)
    else:
        kwargs["password"] = env("SNOWFLAKE_PASSWORD")
    # Cap runtime of any single statement so a runaway query cannot burn trial credits.
    kwargs["session_parameters"] = {"STATEMENT_TIMEOUT_IN_SECONDS": int(os.getenv("DM_STATEMENT_TIMEOUT", "60"))}
    return snowflake.connector.connect(**kwargs)


def run_query(conn, sql: str) -> QueryResult:
    cur = conn.cursor()
    try:
        cur.execute(sql)
        columns = [c[0] for c in cur.description]
        return QueryResult(columns, cur.fetchall(), cur.sfqid)
    finally:
        cur.close()
