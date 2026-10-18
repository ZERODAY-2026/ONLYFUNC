"""Ask one question from the terminal. Run: python -m datamind.cli "your question"  (or: run.bat ask "...")"""
import sys

from .agent import Agent
from .config import load_config
from .snowflake_client import connect


def ask(question: str) -> int:
    conn = connect("SNOWFLAKE_READER_ROLE")
    try:
        a = Agent(conn, load_config()).ask(question)
    finally:
        conn.close()
    print(f"status: {a.status}")
    if a.message:
        print(f"message: {a.message}")
    for note in a.assumptions:
        print(f"assumption: {note}")
    if a.executed_sql or a.sql:
        print(f"sql: {a.executed_sql or a.sql}")
    if a.rows:
        print(f"query id: {a.query_id} | rows: {len(a.rows)}")
        print(" | ".join(a.columns))
        for r in a.rows[:10]:
            print(" | ".join(str(c) for c in r))
    if a.explanation:
        print(f"\n{a.explanation}")
    for w in a.warnings:
        print(f"note: {w}")
    return 0 if a.status in ("answered", "empty", "clarify", "unsupported") else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('usage: python -m datamind.cli "your question"')
        sys.exit(2)
    sys.exit(ask(" ".join(sys.argv[1:])))
