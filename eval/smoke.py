"""Live routing smoke test. Chalao: python -m eval.smoke (ya run.bat smoke). Snowflake aur Gemma chahiye."""
import sys
from pathlib import Path

import yaml

from datamind.agent import Agent
from datamind.config import load_config
from datamind.snowflake_client import connect

ACCEPTED = {"query": {"answered", "empty"}, "clarify": {"clarify"}, "refuse": {"unsupported", "refused"}}


def main() -> int:
    cases = yaml.safe_load((Path(__file__).parent / "smoke_cases.yaml").read_text(encoding="utf-8"))["cases"]
    conn = connect("SNOWFLAKE_READER_ROLE")
    failures = []
    try:
        agent = Agent(conn, load_config())
        for case in cases:
            agent.history.clear()  # cases ek dusre par depend nahi karte
            a = agent.ask(case["question"])
            ok = a.status in ACCEPTED[case["expect"]]
            extra = f" | query id {a.query_id}" if a.query_id else ""
            warn = f" | WARNING: {a.warnings[0]}" if a.warnings else ""
            print(f"{'PASS' if ok else 'FAIL'}  expect {case['expect']:<7} got {a.status:<11} {case['question']}{extra}{warn}")
            if not ok:
                failures.append(f"{case['question']} -> {a.status}: {a.message or a.sql}")
    finally:
        conn.close()
    print(f"\nPassed {len(cases) - len(failures)}/{len(cases)}")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
