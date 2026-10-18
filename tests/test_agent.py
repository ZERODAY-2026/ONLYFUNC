"""Fake model aur fake Snowflake ke saath workflow tests (network nahi). Live runs eval/smoke.py me hain."""
import pytest

from datamind import agent as agent_mod
from datamind.config import load_config
from datamind.llm import LLMError
from datamind.snowflake_client import QueryResult

T = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1"
COUNT_SQL = f"SELECT COUNT(*) AS N FROM {T}.ORDERS"


class Fakes:
    def __init__(self, plans, rows=((42,),), explanation="Snowflake returned 42 orders."):
        self.plans = list(plans)
        self.rows, self.explanation = list(rows), explanation
        self.executed, self.explain_calls = [], 0

    def chat_json(self, system, user):
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        return plan

    def chat_text(self, system, user):
        self.explain_calls += 1
        if isinstance(self.explanation, Exception):
            raise self.explanation
        return self.explanation

    def run_query(self, conn, sql):
        self.executed.append(sql)
        return QueryResult(["N"], self.rows, "qid-123")


@pytest.fixture
def make(monkeypatch):
    def _make(fakes: Fakes):
        monkeypatch.setattr(agent_mod, "describe_schema", lambda conn, cfg: "schema")
        monkeypatch.setattr(agent_mod.llm, "chat_json", fakes.chat_json)
        monkeypatch.setattr(agent_mod.llm, "chat_text", fakes.chat_text)
        monkeypatch.setattr(agent_mod, "run_query", fakes.run_query)
        return agent_mod.Agent(None, load_config())
    return _make


def q(sql, assumptions=()):
    return {"action": "query", "sql": sql, "assumptions": list(assumptions)}


def test_answer_carries_sql_rows_query_id_and_explanation(make):
    f = Fakes([q(COUNT_SQL)])
    a = make(f).ask("How many orders are there?")
    assert a.status == "answered" and a.query_id == "qid-123" and a.rows == [(42,)]
    assert "42" in a.explanation and not a.warnings
    assert len(f.executed) == 1 and "LIMIT" in f.executed[0].upper()


def test_clarify_and_unsupported_never_touch_snowflake(make):
    f = Fakes([{"action": "clarify", "message": "Which metric?"}, {"action": "unsupported", "message": "Read-only."}])
    ag = make(f)
    assert ag.ask("top sales").status == "clarify"
    assert ag.ask("delete customers").status == "unsupported"
    assert f.executed == []


def test_empty_question_asks_for_input_and_too_long_is_refused_without_any_model_call(make):
    f = Fakes([])  # koi bhi model call khaali list se pop karegi aur test fail ho jayega
    ag = make(f)
    assert ag.ask("   ").status == "clarify"
    long = ag.ask("x" * 1001)
    assert long.status == "refused" and "too long" in long.message
    assert f.executed == [] and f.explain_calls == 0


def test_write_sql_is_refused_not_executed(make):
    f = Fakes([q(f"DROP TABLE {T}.ORDERS")])
    a = make(f).ask("drop it")
    assert a.status == "refused" and f.executed == []


def test_invalid_sql_gets_one_repair_attempt(make):
    f = Fakes([q("SELECT COUNT(*) FROM ORDERS"), q(COUNT_SQL)])  # pehla: unqualified table (retryable)
    a = make(f).ask("How many orders?")
    assert a.status == "answered" and len(f.executed) == 1


def test_empty_result_does_not_ask_the_model_to_explain(make):
    f = Fakes([q(COUNT_SQL)], rows=[])
    a = make(f).ask("orders in 2030")
    assert a.status == "empty" and f.explain_calls == 0 and "no rows" in a.message


def test_ungrounded_explanation_is_replaced_by_exact_values(make):
    f = Fakes([q(COUNT_SQL)], explanation="There were 999 fabricated orders.")
    a = make(f).ask("How many orders?")
    assert "999" not in a.explanation and "N: 42" in a.explanation
    assert a.warnings and "not found in the rows" in a.warnings[0]


def test_explanation_failure_still_returns_the_rows(make):
    f = Fakes([q(COUNT_SQL)], explanation=LLMError("Gemma is unavailable"))
    a = make(f).ask("How many orders?")
    assert a.status == "answered" and a.rows == [(42,)] and a.warnings == ["Gemma is unavailable"]


def test_model_down_at_sql_stage_is_an_error_answer(make):
    f = Fakes([LLMError("Gemma is unavailable (ConnectError): refused")])
    a = make(f).ask("How many orders?")
    assert a.status == "error" and "unavailable" in a.message and f.executed == []


def test_answer_changes_when_data_changes(make):
    f = Fakes([q(COUNT_SQL), q(COUNT_SQL)], rows=[(42,)])
    ag = make(f)
    assert "42" in ag.ask("How many orders?").explanation
    f.rows, f.explanation = [(43,)], "Snowflake returned 43 orders."
    second = ag.ask("How many orders?")
    assert "43" in second.explanation and second.rows == [(43,)]
