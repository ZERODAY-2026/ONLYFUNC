"""Follow-up suggestions: context se bante hain, saaf kiye jaate hain, aur fail hone par jawab ko kuch nahi hota (offline, fake model ke saath)."""
import json

import pytest

from datamind import agent as agent_mod
from datamind.chat_store import ChatStore
from datamind.config import load_config
from datamind.llm import LLMError
from datamind.models import Answer


class FakeModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat_json(self, system, user):
        self.calls.append((system, json.loads(user)))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def make(monkeypatch):
    def _make(reply):
        fake = FakeModel(reply)
        monkeypatch.setattr(agent_mod, "describe_schema", lambda conn, cfg: "schema")
        monkeypatch.setattr(agent_mod.llm, "chat_json", fake.chat_json)
        return agent_mod.Agent(None, load_config()), fake
    return _make


def answered(question="How many wines are there?", rows=None):
    return Answer("answered", question, sql="SELECT COUNT(*) AS N FROM UCI.PUBLIC.WINE_QUALITY", columns=["N"],
                  rows=rows or [(6497,)], tables=["UCI.PUBLIC.WINE_QUALITY"], assumptions=["All wines"])


def test_returns_three_clean_suggestions_in_order(make):
    ag, fake = make({"suggestions": ["How many are red?", "  Which quality   is most common? ", "How many wines have no quality score?", "A fourth one"]})
    out = ag.suggest_followups(answered())
    assert out == ["How many are red?", "Which quality is most common?", "How many wines have no quality score?"]


def test_context_reaches_the_model(make):
    ag, fake = make({"suggestions": ["Next?"]})
    ag.history = [("Earlier question", "SELECT 1"), ("How many wines are there?", "SELECT 2")]
    ag.suggest_followups(answered(rows=[(i,) for i in range(30)]))
    system, ctx = fake.calls[0]
    assert ctx["last_question"] == "How many wines are there?"
    assert ctx["earlier_questions"] == ["Earlier question", "How many wines are there?"]
    assert len(ctx["rows"]) == agent_mod.SUGGEST_ROWS and ctx["row_count"] == 30
    assert ctx["columns"] == ["N"] and ctx["tables"] == ["UCI.PUBLIC.WINE_QUALITY"] and ctx["assumptions"] == ["All wines"]
    assert "wine_quality" in system and "tpch" in system            # chale hue saare datasets prompt me


def test_prompt_lists_only_the_datasets_switched_on(make):
    ag, fake = make({"suggestions": ["Next?"]})
    ag.set_scope(["wine_quality"])
    ag.suggest_followups(answered())
    system = fake.calls[0][0]
    assert "wine_quality" in system and "tpch" not in system and "owid" not in system


def test_repeats_and_junk_are_dropped(make):
    ag, _ = make({"suggestions": [
        "How many wines are there?",             # abhi poocha hua sawal
        "how many wines are there?  ",           # wahi, case/space alag
        "Earlier question",                      # pehle ka sawal
        "", "   ", 42, None, {"q": "x"},         # kachra
        "x" * 200,                               # bahut lamba
        "SELECT * FROM UCI.PUBLIC.WINE_QUALITY", # SQL, sawal nahi
        "What is the average alcohol?",
        "What is the average alcohol?",          # duplicate
        "Which color has more wines?",
    ]})
    ag.history = [("Earlier question", "SELECT 1")]
    assert ag.suggest_followups(answered()) == ["What is the average alcohol?", "Which color has more wines?"]


@pytest.mark.parametrize("status", ["clarify", "unsupported", "refused", "error"])
def test_no_model_call_when_there_is_nothing_to_follow_up(make, status):
    ag, fake = make({"suggestions": ["Never used"]})
    assert ag.suggest_followups(Answer(status, "q", message="m")) == []
    assert fake.calls == []


def test_empty_result_still_gets_suggestions(make):
    ag, fake = make({"suggestions": ["Try another year?"]})
    a = Answer("empty", "How many orders in 2030?", sql="SELECT 1", columns=["N"], rows=[])
    assert ag.suggest_followups(a) == ["Try another year?"] and len(fake.calls) == 1


@pytest.mark.parametrize("reply", [LLMError("Gemma is unavailable"), RuntimeError("boom"),
                                   {"action": "unsupported", "message": "unreadable"}, {"suggestions": None}, {"suggestions": "text"}])
def test_failures_and_garbage_never_break_the_answer(make, reply):
    ag, _ = make(reply)
    assert ag.suggest_followups(answered()) == []


def test_suggestions_survive_save_and_reload(tmp_path):
    store = ChatStore(tmp_path)
    a = answered()
    a.suggestions = ["How many are red?", "Which quality is most common?"]
    chat_id = store.create(a.question)
    store.append(chat_id, a)
    _, answers = ChatStore(tmp_path).load(chat_id)
    assert answers[0].suggestions == a.suggestions


def test_old_saved_chats_without_the_field_still_load(tmp_path):
    store = ChatStore(tmp_path)
    chat_id = store.create("Old chat")
    store.append(chat_id, answered())
    path = tmp_path / f"{chat_id}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    del saved["answers"][0]["suggestions"]                 # purani file jisme yeh field nahi tha
    path.write_text(json.dumps(saved), encoding="utf-8")
    _, answers = ChatStore(tmp_path).load(chat_id)
    assert answers[0].suggestions == []
