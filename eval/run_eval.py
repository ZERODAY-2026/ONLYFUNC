"""Asli stack par ground-truth evaluation. Chalao: python -m eval.run_eval  (ya: run.bat eval)

  --only c01,j02     sirf yeh case ids chalao         --category ranking   sirf ek category chalao
  --truth-only       truth rows print karke ruk jao (naye case ko check karne ke liye)
  --min-pass 0.8     pass rate isse kam ho toh non-zero exit
eval/results/latest.json aur latest.md likhta hai (submission ka evidence)."""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from datamind import llm, trace
from datamind.agent import Agent
from datamind.config import load_config
from datamind.logs import get_logger
from datamind.snowflake_client import connect, run_query
from eval.compare import match

HERE = Path(__file__).parent
TOKENS = {"{TPCH}": "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1", "{WINE}": "UCI.PUBLIC.WINE_QUALITY", "{UCI}": "UCI.PUBLIC", "{OWID}": "OWID.PUBLIC", "{DS}": "SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL"}
REFUSED = {"unsupported", "refused"}
log = get_logger()


def fill(sql: str) -> str:
    for token, value in TOKENS.items():
        sql = sql.replace(token, value)
    return sql


def judge_split(case: dict, final, conn) -> tuple[bool, str, list]:
    """Multipart: har truth ke liye koi ek part (kisi bhi order me) ke rows match hone chahiye, aur parts ki ginti wahi honi chahiye."""
    parts = case["parts"]
    if final.status != "answered" or not final.steps:
        return False, f"status {final.status} without parts: {final.message[:120]}", []
    if len(final.steps) != len(parts):
        return False, f"expected {len(parts)} parts, got {len(final.steps)}", []
    unused, truths = list(final.steps), []
    for i, part in enumerate(parts, 1):
        rows = run_query(conn, fill(part["truth"])).rows
        truths += rows
        hit = next((s for s in unused if s.status in ("answered", "empty") and match(rows, s.rows, part.get("compare", "rows"), False)[0]), None)
        if hit is None:
            got = [(s.question, s.status, [list(map(str, r)) for r in s.rows[:2]]) for s in unused]
            return False, f"no part matched truth {i} ({[list(map(str, r)) for r in rows[:2]]}); parts: {got}", truths
        unused.remove(hit)
    return True, "", truths


def judge(case: dict, final, conn) -> tuple[bool, str, list]:
    """(passed, reason, truth_rows) lautata hai."""
    expect = case.get("expect", "query")
    if expect == "refuse":
        return final.status in REFUSED, f"status {final.status}" if final.status not in REFUSED else "", []
    if expect == "clarify":
        return final.status == "clarify", f"status {final.status}" if final.status != "clarify" else "", []
    if expect == "ambiguous":
        ok = final.status == "clarify" or (final.status == "answered" and bool(final.assumptions))
        return ok, "" if ok else f"status {final.status} without stated assumptions", []
    if expect == "split":
        return judge_split(case, final, conn)
    if final.status not in ("answered", "empty"):
        return False, f"status {final.status}: {final.message}", []
    truth_rows = run_query(conn, fill(case["truth"])).rows
    ok, reason = match(truth_rows, final.rows, case.get("compare", "rows"), bool(case.get("ordered")))
    return ok, reason, truth_rows


def run_case(agent: Agent, conn, case: dict) -> dict:
    agent.history.clear()
    turns = case.get("turns") or [case["question"]]
    trace.emit("EVAL", f"case {case['id']} ({case['category']}, expect {case.get('expect', 'query')}): {len(turns)} turn(s)")
    started = time.time()
    record = {"id": case["id"], "category": case["category"], "questions": turns, "expect": case.get("expect", "query")}
    try:
        answers = [agent.ask(q) for q in turns]
        final = answers[-1]
        ok, reason, truth_rows = judge(case, final, conn)
        record.update(
            verdict="PASS" if ok else "FAIL", reason=reason, status=final.status, query_id=final.query_id,
            answer_sql=final.executed_sql or final.sql, truth_sql=fill(case.get("truth", "")).strip(),
            answer_rows=[list(map(str, r)) for r in final.rows[:5]], truth_rows=[list(map(str, r)) for r in truth_rows[:5]],
            assumptions=final.assumptions, warnings=final.warnings, message=final.message)
    except Exception as e:  # crash ko failure ki tarah wajah ke saath record karna hai, kabhi chhupana nahi
        log.exception("eval case %s crashed", case["id"])
        record.update(verdict="FAIL", reason=f"crashed: {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", status="crash")
    record["seconds"] = round(time.time() - started, 1)
    return record


def write_reports(results: list[dict]) -> None:
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    passed = sum(r["verdict"] == "PASS" for r in results)
    meta = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": llm.model_name(),
            "cases": len(results), "passed": passed, "pass_rate": round(passed / len(results), 3)}
    (out / "latest.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2, default=str), encoding="utf-8")

    by_cat = defaultdict(lambda: [0, 0])
    for r in results:
        by_cat[r["category"]][1] += 1
        by_cat[r["category"]][0] += r["verdict"] == "PASS"
    lines = [f"# Evaluation results", "",
             f"Model `{meta['model']}` | {meta['date']} | **{passed}/{len(results)} passed ({meta['pass_rate']:.0%})**", "",
             "| Category | Passed |", "|---|---|"]
    lines += [f"| {c} | {p}/{n} |" for c, (p, n) in sorted(by_cat.items())]
    lines += ["", "| Id | Verdict | Question | Status | Snowflake query id | Note |", "|---|---|---|---|---|---|"]
    for r in results:
        q = " / ".join(r["questions"]).replace("|", "/")
        lines.append(f"| {r['id']} | {r['verdict']} | {q} | {r.get('status', '')} | {r.get('query_id', '')} | {r.get('reason', '')} |")
    (out / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--category")
    ap.add_argument("--truth-only", action="store_true")
    ap.add_argument("--min-pass", type=float, default=0.0)
    args = ap.parse_args()

    cases = yaml.safe_load((HERE / "questions.yaml").read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]

    conn = connect("SNOWFLAKE_READER_ROLE")
    try:
        if args.truth_only:
            for c in cases:
                if "truth" in c:
                    rows = run_query(conn, fill(c["truth"])).rows
                    print(f"{c['id']}  {' / '.join(c.get('turns') or [c['question']])}\n    -> {[list(map(str, r)) for r in rows[:6]]}")
                for n, part in enumerate(c.get("parts") or [], 1):
                    rows = run_query(conn, fill(part["truth"])).rows
                    print(f"{c['id']}  part {n} of: {c['question']}\n    -> {[list(map(str, r)) for r in rows[:6]]}")
            return 0
        agent = Agent(conn, load_config())
        results = []
        for case in cases:
            r = run_case(agent, conn, case)
            results.append(r)
            print(f"{r['verdict']}  {r['id']:<4} {r['category']:<11} {r['seconds']:>5}s  {' / '.join(r['questions'])}"
                  + (f"\n        -> {r['reason']}" if r["verdict"] == "FAIL" else ""), flush=True)
        write_reports(results)
    finally:
        conn.close()
    passed = sum(r["verdict"] == "PASS" for r in results)
    rate = passed / len(results) if results else 0.0
    print(f"\nPassed {passed}/{len(results)} ({rate:.0%}). Report: eval/results/latest.md")
    return 0 if rate >= args.min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
