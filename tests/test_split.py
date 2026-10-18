"""Multipart sawal: alag datasets ke hisse alag single-dataset child agents se, wahi validator, koi merged number nahi (offline, fakes ke saath)."""
import pytest

from datamind import agent as agent_mod
from datamind.chat_store import ChatStore
from datamind.config import load_config
from datamind.models import Answer
from datamind.snowflake_client import QueryResult

STUDENTS = "SELECT COUNT(*) AS N FROM UCI.PUBLIC.STUDENT_PERFORMANCE"
FRANCE = "SELECT POPULATION FROM OWID.PUBLIC.POPULATION WHERE ENTITY = 'France' AND YEAR = 2020"
WINE = "SELECT AVG(ALCOHOL) AS A FROM UCI.PUBLIC.WINE_QUALITY"
SPLIT = {"action": "split", "message": "", "parts": [
    {"question": "How many students are there?", "dataset": "student_performance"},
    {"question": "What was France's population in 2020?", "dataset": "owid"}]}


class Fakes:
    """chat_json ko pehle parent ka plan, phir har part ka plan dena hai (parts ek ke baad ek chalte hain)."""
    def __init__(self, plans, rows=None):
        self.plans, self.systems, self.executed = list(plans), [], []
        self.rows = rows or {"STUDENT_PERFORMANCE": [(649,)], "POPULATION": [(65905273,)], "WINE_QUALITY": [(10.4,)]}

    def chat_json(self, system, user):
        self.systems.append(system)
        return self.plans.pop(0)

    def chat_text(self, system, user):
        return "The answer is shown in the rows."

    def run_query(self, conn, sql):
        self.executed.append(sql)
        key = next(k for k in self.rows if k in sql)
        return QueryResult(["V"], self.rows[key], f"qid-{len(self.executed)}")


@pytest.fixture
def make(monkeypatch):
    def _make(plans, **kw):
        fake = Fakes(plans, **kw)
        monkeypatch.setattr(agent_mod, "describe_schema", lambda conn, cfg: "-- Dataset schema: " + ", ".join(d.name for d in cfg.datasets))
        monkeypatch.setattr(agent_mod.llm, "chat_json", fake.chat_json)
        monkeypatch.setattr(agent_mod.llm, "chat_text", fake.chat_text)
        monkeypatch.setattr(agent_mod, "run_query", fake.run_query)
        return agent_mod.Agent(None, load_config()), fake
    return _make


def q(sql):
    return {"action": "query", "sql": sql, "assumptions": ["its own dataset"]}


def test_a_split_question_is_answered_part_by_part_with_no_merged_number(make):
    ag, fake = make([SPLIT, q(STUDENTS), q(FRANCE)])
    a = ag.ask("How many students are there, and what was France's population in 2020?")
    assert a.status == "answered" and len(a.steps) == 2
    assert [s.rows for s in a.steps] == [[(649,)], [(65905273,)]]
    assert [s.query_id for s in a.steps] == ["qid-1", "qid-2"] and a.query_id == "qid-1, qid-2"
    assert "Part 1 · student performance" in a.explanation and "Part 2 · owid" in a.explanation
    assert "no combined figure is calculated" in a.explanation
    assert a.rows == [] and a.columns == []                              # koi merged table nahi
    assert "-- Part 1" in a.sql and "-- Part 2" in a.sql and STUDENTS in a.sql and FRANCE in a.sql
    assert a.tables == ["UCI.PUBLIC.STUDENT_PERFORMANCE", "OWID.PUBLIC.POPULATION"]
    assert a.assumptions == ["Part 1: its own dataset", "Part 2: its own dataset"]


def test_each_part_is_confined_to_its_own_dataset(make):
    """Part 1 owid ki table par SQL likhe toh wahi validator refuse karta hai: part 1 sirf student_performance dekhta hai."""
    ag, fake = make([SPLIT, q(FRANCE), q(FRANCE)])
    a = ag.ask("students and France")
    assert a.steps[0].status == "refused" and a.steps[1].status == "answered"
    assert len(fake.executed) == 1 and "OWID.PUBLIC.POPULATION" in fake.executed[0]   # sirf part 2 Snowflake tak pahunchi
    child_prompts = fake.systems[1:]
    assert "student_performance" in child_prompts[0] and "owid" not in child_prompts[0]


def test_a_failed_part_does_not_hide_the_part_that_worked(make):
    ag, _ = make([SPLIT, q(FRANCE), q(FRANCE)])            # part 1 galat dataset ki table maangta hai -> refused
    a = ag.ask("students and France")
    assert a.status == "answered" and len(a.steps) == 2
    assert "This part could not be answered" in a.explanation
    assert [s.status for s in a.steps] == ["refused", "answered"]
    assert a.query_id == "qid-1"                            # sirf kaam kiye hue part ka ID


def test_if_no_part_works_the_answer_is_an_error_with_the_reasons(make):
    ag, _ = make([SPLIT, q(FRANCE), q(STUDENTS)])           # dono galat dataset
    a = ag.ask("students and France")
    assert a.status == "error" and len(a.steps) == 2 and "None of the parts could be answered" in a.message


def test_parts_in_one_dataset_are_not_a_real_split(make):
    plan = {"action": "split", "parts": [{"question": "How many wines?", "dataset": "wine_quality"},
                                         {"question": "Average alcohol?", "dataset": "wine_quality"}]}
    ag, fake = make([plan, q(WINE)])
    a = ag.ask("wines")
    assert a.status == "answered" and a.steps == [] and a.rows == [(10.4,)]   # seedha us dataset se ek normal jawab


def test_a_single_valid_part_is_just_asked_of_that_dataset(make):
    ag, fake = make([{"action": "split", "parts": [{"question": "x", "dataset": "owid"}]}, q(FRANCE)])
    a = ag.ask("France 2020 population")
    assert a.status == "answered" and a.steps == [] and a.rows == [(65905273,)]


@pytest.mark.parametrize("parts", [None, "text", [], [{"question": "x", "dataset": "nope"}, {"question": "y", "dataset": "nope2"}]])
def test_a_bad_split_plan_is_refused_politely_and_runs_nothing(make, parts):
    ag, fake = make([{"action": "split", "parts": parts, "message": "needs two datasets"}])
    a = ag.ask("odd question")
    assert a.status == "unsupported" and fake.executed == []


def test_at_most_three_distinct_parts_are_used(make):
    parts = [{"question": f"Q{i}", "dataset": ds} for i, ds in enumerate(["owid", "wine_quality", "student_performance", "bank_marketing"])]
    parts.insert(1, {"question": "q0", "dataset": "owid"})  # Q0 ka duplicate (case alag): pehle hatega, phir 3 ki limit
    ag, fake = make([{"action": "split", "parts": parts}, q(FRANCE), q(WINE), q(STUDENTS)])
    a = ag.ask("many things")
    assert len(a.steps) == 3 and [s.question for s in a.steps] == ["Q0", "Q1", "Q2"]


def test_a_child_can_never_split_again(make):
    ag, fake = make([SPLIT, {"action": "split", "parts": SPLIT["parts"]}, q(FRANCE)])
    a = ag.ask("students and France")
    assert a.steps[0].status == "unsupported" and a.steps[1].status == "answered"   # koi recursion nahi


def test_the_split_rule_is_only_in_prompts_that_can_split(make):
    ag, _ = make([])
    assert "split" in ag.system and "separate facts" in ag.system
    ag.set_scope(["wine_quality"])                                       # ek dataset: split ka matlab nahi
    assert "separate facts" not in ag.system
    ag.set_scope(["wine_quality", "owid"])
    assert "separate facts" in ag.system
    assert "separate facts" not in ag._child("owid").system              # child ke prompt me bhi nahi


def test_dm_multipart_off_removes_the_feature_completely(make, monkeypatch):
    monkeypatch.setenv("DM_MULTIPART", "0")
    ag, fake = make([SPLIT])
    assert "separate facts" not in ag.system
    a = ag.ask("students and France")
    assert a.status == "unsupported" and a.steps == [] and fake.executed == []


def test_follow_ups_can_refer_to_the_parts_and_no_suggestions_for_a_split(make):
    ag, _ = make([SPLIT, q(STUDENTS), q(FRANCE)])
    a = ag.ask("students and France")
    assert [h[1] for h in ag.history] == [STUDENTS, FRANCE]
    assert ag.suggest_followups(a) == []


def test_children_are_cached_and_cleared_when_the_scope_changes(make):
    ag, _ = make([])
    first = ag._child("owid")
    assert ag._child("owid") is first
    ag.set_scope(["owid", "wine_quality"])
    assert ag._child("owid") is not first


def test_a_split_answer_survives_save_and_reload(make, tmp_path):
    ag, _ = make([SPLIT, q(STUDENTS), q(FRANCE)])
    a = ag.ask("students and France")
    store = ChatStore(tmp_path)
    chat_id = store.create(a.question)
    store.append(chat_id, a)
    _, answers = ChatStore(tmp_path).load(chat_id)
    back = answers[0]
    assert all(isinstance(s, Answer) for s in back.steps) and len(back.steps) == 2
    assert back.steps[1].query_id == "qid-2" and back.steps[0].tables == ["UCI.PUBLIC.STUDENT_PERFORMANCE"]


def test_old_answers_without_steps_still_load():
    assert Answer("answered", "q").steps == []
