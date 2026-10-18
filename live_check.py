"""Live check of the Snowflake layer against your real account. Run: python live_check.py

Uses only the executor (the same object the AI layer will call). Exit code 0 only if every check passes."""
import sys

import snowflake.connector.errors as sf_errors

from datamind.executor import make_executor

T = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1"
results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((ok, name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    ex = make_executor(max_rows=1000)
    try:
        r = ex("SELECT CURRENT_ROLE() AS ROLE_NAME, CURRENT_WAREHOUSE() AS WH")
        check("logs in with the read-only role", r["rows"][0]["ROLE_NAME"] == "DM_READER", str(r["rows"][0]))

        r = ex(f"SELECT COUNT(*) AS N FROM {T}.ORDERS")
        check("TPC-H ORDERS has 1,500,000 rows", r["rows"][0]["N"] == 1500000, f"query id {r['query_id']}")

        r = ex(f"SELECT COUNT(*) AS N FROM {T}.CUSTOMER")
        check("TPC-H CUSTOMER has 150,000 rows", r["rows"][0]["N"] == 150000, f"query id {r['query_id']}")

        r = ex(f"SELECT R.R_NAME, COUNT(*) AS N FROM {T}.CUSTOMER C JOIN {T}.NATION NA ON C.C_NATIONKEY = NA.N_NATIONKEY "
               f"JOIN {T}.REGION R ON NA.N_REGIONKEY = R.R_REGIONKEY GROUP BY R.R_NAME ORDER BY R.R_NAME")
        check("a 3-table join returns 5 regions as dict rows", len(r["rows"]) == 5 and set(r["rows"][0]) == {"R_NAME", "N"}, str(r["rows"][0]))

        r = ex(f"SELECT O_ORDERKEY FROM {T}.ORDERS")
        check("result cap truncates a big result (1000 rows, truncated flag)", len(r["rows"]) == 1000 and r["truncated"] is True)

        r = ex("SELECT COUNT(*) AS N FROM UCI.PUBLIC.WINE_QUALITY")
        check("second dataset readable (WINE_QUALITY 6,497 rows)", r["rows"][0]["N"] == 6497)

        try:
            ex("SELECT * FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.NO_SUCH_TABLE")
            check("a bad table raises a SQL error for the caller to repair", False, "no error raised")
        except sf_errors.ProgrammingError as e:
            check("a bad table raises a SQL error for the caller to repair", True, f"errno {e.errno}")

        for bad in ("DROP TABLE UCI.PUBLIC.WINE_QUALITY", "DELETE FROM UCI.PUBLIC.WINE_QUALITY"):
            try:
                ex(bad)
                check(f"executor refuses: {bad.split()[0]}", False, "it ran!")
            except ValueError:
                check(f"executor refuses: {bad.split()[0]}", True)
    finally:
        ex.close()
    failed = [name for ok, name in results if not ok]
    print(f"\nPassed {len(results) - len(failed)}/{len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
