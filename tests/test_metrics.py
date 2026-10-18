"""Cost aur reliability: trace lines se hisaab. Sirf wahi gina jaata hai jo code ne record kiya; estimate saaf estimate rehta hai (offline)."""
import pytest

from datamind import metrics
from datamind.models import Answer


def line(tag, message, ms=0):
    return {"time": "19:00:00.000", "ms": ms, "tag": tag, "message": message}


def answered(question="q", sql_ms=200, gemma_ms=(2000, 1800), total=4400, qid="01c7-aaa", extra=()):
    trace = [line("ASK", "question received"), line("GEMMA", "-> gemma4:31b"),
             line("GEMMA", f"<- ok {gemma_ms[0]} ms response_chars=10", gemma_ms[0]),
             line("PLAN", "attempt 1: Gemma chose action='query'"),
             line("VALIDATE", "accepted: read-only"),
             line("SQL", "-> 100 chars: SELECT 1"),
             line("SQL", f"<- ok {sql_ms} ms query_id={qid} columns=1 rows=1 result_chars=5", 2500),
             line("GEMMA", f"<- ok {gemma_ms[1]} ms response_chars=20", 4300), *extra, line("ASK", "answer ready", total)]
    return Answer("answered", question, sql="SELECT 1", trace=trace)


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    monkeypatch.delenv("DM_WAREHOUSE_CREDITS_PER_HOUR", raising=False)
    monkeypatch.delenv("DM_CREDIT_BUDGET", raising=False)


def test_counts_calls_statements_and_time_from_the_trace():
    m = metrics.summarize([answered("a", total=4400), answered("b", sql_ms=800, total=6200, qid="01c7-bbb")])
    assert m["questions"] == 2 and m["traced"] == 2 and m["untraced"] == 0
    assert m["gemma_calls"] == 4 and m["gemma_ms"] == 2 * (2000 + 1800)
    assert m["statements"] == 2 and m["statement_ms"] == 1000
    assert m["median_ms"] == 5300 and m["max_ms"] == 6200
    assert [s["query_id"] for s in m["slowest"]] == ["01c7-bbb", "01c7-aaa"] and m["slowest"][0]["question"] == "b"


def test_estimated_credits_are_query_time_times_the_warehouse_rate(monkeypatch):
    a = [answered(sql_ms=1_800_000)]                                    # 30 minute ki query
    assert metrics.summarize(a)["estimated_credits"] == pytest.approx(0.5)            # XSMALL: 1 credit/ghanta
    monkeypatch.setenv("DM_WAREHOUSE_CREDITS_PER_HOUR", "4")                            # MEDIUM
    assert metrics.summarize(a)["estimated_credits"] == pytest.approx(2.0)
    monkeypatch.setenv("DM_WAREHOUSE_CREDITS_PER_HOUR", "garbage")
    assert metrics.summarize(a)["estimated_credits"] == pytest.approx(0.5)            # kharab value par default


def test_budget_is_optional_and_reports_how_much_is_used(monkeypatch):
    a = [answered(sql_ms=1_800_000)]
    m = metrics.summarize(a)
    assert m["budget"] is None and m["budget_used"] is None
    monkeypatch.setenv("DM_CREDIT_BUDGET", "2")
    m = metrics.summarize(a)
    assert m["budget"] == 2 and m["budget_used"] == pytest.approx(0.25)
    for bad in ("0", "-1", "abc"):
        monkeypatch.setenv("DM_CREDIT_BUDGET", bad)
        assert metrics.summarize(a)["budget"] is None


def test_failures_retries_and_rejections_are_counted():
    extra = [line("VALIDATE", "REJECTED (retryable): Qualify JOIN columns with the table alias."),
             line("PLAN", "attempt 2: Gemma chose action='query'"),
             line("SQL", "Snowflake rejected the query (errno 904): invalid identifier"),
             line("GEMMA", "<- FAILED after 120 ms: LLMError: Gemma is unavailable")]
    failed = Answer("error", "bad", message="Gemma is unavailable", trace=[line("ASK", "question received")] + extra + [line("ASK", "answer ready", 900)])
    m = metrics.summarize([answered(), failed])
    assert m["validator_rejections"] == 1 and m["retries"] == 1 and m["snowflake_rejections"] == 1 and m["gemma_failures"] == 1
    assert m["errors"] == 1 and m["status"] == {"answered": 1, "error": 1}


def test_old_answers_without_a_trace_are_counted_but_not_guessed():
    m = metrics.summarize([Answer("answered", "old"), answered()])
    assert m["questions"] == 2 and m["untraced"] == 1 and m["traced"] == 1
    assert m["statements"] == 1                                         # sirf traced answer ka kaam


def test_an_empty_session_has_no_division_by_zero():
    m = metrics.summarize([])
    assert m["questions"] == 0 and m["median_ms"] == 0 and m["max_ms"] == 0 and m["estimated_credits"] == 0 and m["slowest"] == []


def test_only_the_three_slowest_statements_are_kept():
    m = metrics.summarize([answered(f"q{i}", sql_ms=100 * (i + 1), qid=f"id{i}") for i in range(6)])
    assert [s["query_id"] for s in m["slowest"]] == ["id5", "id4", "id3"]


def test_a_multipart_answer_is_one_question_with_all_its_statements():
    a = answered("two parts")
    a.trace += [line("SQL", "<- ok 300 ms query_id=01c7-second columns=1 rows=1 result_chars=5", 6000), line("ASK", "answer ready", 6500)]
    m = metrics.summarize([a])
    assert m["questions"] == 1 and m["statements"] == 2 and m["statement_ms"] == 500
