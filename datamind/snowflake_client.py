"""All data access goes through Snowflake. Nothing is answered from local files."""
import os
from dataclasses import dataclass

import snowflake.connector

from . import trace
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
    timeout = int(os.getenv("DM_STATEMENT_TIMEOUT", "60"))
    kwargs["session_parameters"] = {"STATEMENT_TIMEOUT_IN_SECONDS": timeout}
    auth = "key-pair" if key_file else ("access token" if pat else "password")  # the method only, never the secret
    trace.install_network_trace()
    with trace.span("SNOWFLAKE", f"connect account={kwargs['account']} user={kwargs['user']} role={kwargs['role']} "
                                  f"warehouse={kwargs['warehouse']} auth={auth} statement_timeout={timeout}s") as info:
        conn = snowflake.connector.connect(**kwargs)
        info["session_id"] = conn.session_id
    return conn


def run_query(conn, sql: str) -> QueryResult:
    cur = conn.cursor()
    try:
        with trace.span("SQL", f"{len(sql)} chars: {trace.short(sql)}") as info:
            cur.execute(sql)
            columns = [c[0] for c in cur.description]
            rows = cur.fetchall()
            info.update(query_id=cur.sfqid, columns=len(columns), rows=len(rows),
                        result_chars=sum(len(str(cell)) for row in rows for cell in row))
        return QueryResult(columns, rows, cur.sfqid)
    finally:
        cur.close()
