"""Per-question trace capture (UI ka Trace tab): terminal trace band ho tab bhi lines jama hoti hain, aur users ki lines mix nahi hoti (offline)."""
import json
import threading

import pytest

from datamind import agent as agent_mod
from datamind import trace
from datamind.chat_store import ChatStore
from datamind.config import load_config
from datamind.models import Answer
from datamind.snowflake_client import QueryResult


@pytest.fixture(autouse=True)
def terminal_trace_off(monkeypatch):
    monkeypatch.delenv("DM_TRACE", raising=False)
    monkeypatch.setattr(trace, "_capture_wanted", False)


def test_capture_collects_lines_even_when_the_terminal_trace_is_off(capsys):
    with trace.capture() as lines:
        trace.emit("ASK", "question received")
        trace.emit("SQL", "-> 10 chars: SELECT 1")
    assert [(l["tag"], l["message"]) for l in lines] == [("ASK", "question received"), ("SQL", "-> 10 chars: SELECT 1")]
    assert capsys.readouterr().err == ""                      # terminal par kuch print nahi hua


def test_each_line_has_a_clock_time_and_a_growing_offset():
    with trace.capture() as lines:
        trace.emit("A", "one")
        trace.emit("B", "two")
    for l in lines:
        assert set(l) == {"time", "ms", "tag", "message"} and l["time"][2] == ":" and l["time"][5] == ":"
    assert 0 <= lines[0]["ms"] <= lines[1]["ms"]


def test_lines_outside_a_capture_are_not_kept_and_nothing_leaks_after_it():
    with trace.capture() as lines:
        trace.emit("A", "inside")
    trace.emit("A", "outside")
    assert [l["message"] for l in lines] == ["inside"]


def test_terminal_trace_and_capture_work_together(monkeypatch, capsys):
    monkeypatch.setenv("DM_TRACE", "1")
    with trace.capture() as lines:
        trace.emit("SQL", "hello")
    assert len(lines) == 1 and "hello" in capsys.readouterr().err


def test_spans_are_captured_including_failures():
    with trace.capture() as lines:
        with trace.span("SQL", "start") as info:
            info.update(rows=3, query_id="abc")
        with pytest.raises(ValueError):
            with trace.span("GEMMA", "call"):
                raise ValueError("boom")
    messages = [l["message"] for l in lines]
    assert messages[0] == "-> start" and "rows=3" in messages[1] and "query_id=abc" in messages[1]
    assert any("FAILED" in m and "ValueError: boom" in m for m in messages)


def test_two_threads_do_not_mix_their_lines():
    results = {}

    def work(name):
        with trace.capture() as lines:
            for i in range(50):
                trace.emit("T", f"{name}-{i}")
        results[name] = [l["message"] for l in lines]

    threads = [threading.Thread(target=work, args=(n,)) for n in ("a", "b", "c")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    for name, msgs in results.items():
        assert msgs == [f"{name}-{i}" for i in range(50)]


def test_nested_capture_restores_the_outer_one():
    with trace.capture() as outer:
        trace.emit("A", "outer-1")
        with trace.capture() as inner:
            trace.emit("A", "inner")
        trace.emit("A", "outer-2")
    assert [l["message"] for l in outer] == ["outer-1", "outer-2"] and [l["message"] for l in inner] == ["inner"]


def test_ui_capture_switches_the_network_hooks_on_even_without_dm_trace():
    assert trace.httpx_hooks("ollama") == {}                  # na terminal trace, na UI capture
    trace.enable_capture()
    hooks = trace.httpx_hooks("ollama")
    assert hooks and hooks["request"] and hooks["response"]


def test_a_real_question_leaves_the_workflow_steps_in_the_capture(monkeypatch):
    monkeypatch.setattr(agent_mod, "describe_schema", lambda conn, cfg: "schema")
    monkeypatch.setattr(agent_mod.llm, "chat_json", lambda system, user: {"action": "query", "assumptions": ["All wines"],
                        "sql": "SELECT COUNT(*) AS N FROM UCI.PUBLIC.WINE_QUALITY"})
    monkeypatch.setattr(agent_mod.llm, "chat_text", lambda system, user: "There are 6497 wines.")
    monkeypatch.setattr(agent_mod, "run_query", lambda conn, sql: QueryResult(["N"], [(6497,)], "qid-1"))
    ag = agent_mod.Agent(None, load_config())
    with trace.capture() as lines:
        answer = ag.ask("How many wines are there?")
    tags = [l["tag"] for l in lines]
    assert answer.status == "answered"
    assert tags[0] == "ASK" and tags[-1] == "ASK" and "PLAN" in tags and "VALIDATE" in tags
    assert any("accepted: read-only" in l["message"] for l in lines if l["tag"] == "VALIDATE")
    assert "query_id=qid-1" in lines[-1]["message"]


def test_the_trace_is_saved_with_the_answer_and_old_chats_still_load(tmp_path):
    store = ChatStore(tmp_path)
    with trace.capture() as lines:
        trace.emit("ASK", "question received")
    a = Answer("answered", "q", sql="SELECT 1", columns=["N"], rows=[(1,)], trace=lines)
    chat_id = store.create("q")
    store.append(chat_id, a)
    assert ChatStore(tmp_path).load(chat_id)[1][0].trace == lines
    path = tmp_path / f"{chat_id}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    del saved["answers"][0]["trace"]                          # purani file jisme trace field nahi tha
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert ChatStore(tmp_path).load(chat_id)[1][0].trace == []
