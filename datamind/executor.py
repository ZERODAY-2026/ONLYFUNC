"""Snowflake executor: the callable the AI layer hands validated SQL to.

Contract (matches the teammate's `agent.ask(question, executor)`):
    executor(sql) -> {"rows": [{COLUMN: value, ...}, ...], "columns": [...], "query_id": "...", "truncated": bool}

Behaviour:
- Only SELECT / WITH statements run (defence in depth; the app role is read-only too).
- SQL errors (ProgrammingError) are raised unchanged so the caller can repair the SQL.
- An expired or lost session is re-opened once and the query retried; a second failure is raised.
"""
import re

import snowflake.connector.errors as sf_errors

from .logs import get_logger
from .snowflake_client import connect

log = get_logger()

SESSION_ERRNOS = {390111, 390114}  # session no longer exists / authentication token expired
_READ_ONLY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _unique(names: list[str]) -> list[str]:
    """Column names usable as dict keys: a repeated name gets _2, _3 ... instead of silently overwriting."""
    seen: dict[str, int] = {}
    out = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


class SnowflakeExecutor:
    def __init__(self, role_var: str = "SNOWFLAKE_READER_ROLE", max_rows: int = 1000, connect_fn=connect):
        self.role_var, self.max_rows, self._connect_fn = role_var, max_rows, connect_fn
        self._conn = None

    def __call__(self, sql: str) -> dict:
        if not isinstance(sql, str) or not _READ_ONLY.match(sql):
            raise ValueError("The executor only runs SELECT or WITH statements.")
        for attempt in (1, 2):
            try:
                return self._execute(sql)
            except sf_errors.ProgrammingError:
                raise  # a SQL problem, not a connection problem: never retried here
            except (sf_errors.OperationalError, sf_errors.DatabaseError) as e:
                lost = isinstance(e, sf_errors.OperationalError) or getattr(e, "errno", None) in SESSION_ERRNOS
                if attempt == 2 or not lost:
                    raise
                log.warning("Snowflake session lost (%s); reconnecting once", type(e).__name__)
                self.close()
        raise RuntimeError("unreachable")  # pragma: no cover

    def _execute(self, sql: str) -> dict:
        if self._conn is None or self._conn.is_closed():
            self._conn = self._connect_fn(self.role_var)
        cur = self._conn.cursor()
        try:
            cur.execute(sql)
            columns = _unique([c[0] for c in cur.description])
            fetched = cur.fetchmany(self.max_rows + 1)
            rows = fetched[: self.max_rows]
            return {
                "rows": [dict(zip(columns, r)) for r in rows],
                "columns": columns,
                "query_id": cur.sfqid,
                "truncated": len(fetched) > self.max_rows,
            }
        finally:
            cur.close()

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # closing a dead session may fail; nothing more to do, but keep the trace
                log.exception("Error while closing the Snowflake connection")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def make_executor(**kwargs) -> SnowflakeExecutor:
    """executor = make_executor(); result = executor("SELECT ..."); executor.close() when finished."""
    return SnowflakeExecutor(**kwargs)
