"""The live trace (run.bat console): quiet by default, reports sizes and timings, never prints secrets."""
import httpx
import pytest

from datamind import trace


def test_off_by_default_prints_nothing(monkeypatch, capsys):
    monkeypatch.delenv("DM_TRACE", raising=False)
    trace.emit("SQL", "hello")
    with trace.span("SQL", "start"):
        pass
    assert capsys.readouterr().err == ""


def test_on_prints_one_line_with_tag_and_time(monkeypatch, capsys):
    monkeypatch.setenv("DM_TRACE", "1")
    trace.emit("SQL", "hello")
    line = capsys.readouterr().err.strip()
    assert "SQL" in line and line.endswith("hello") and line[2] == ":"   # HH:MM:SS.mmm prefix


def test_span_reports_start_and_result_fields(monkeypatch, capsys):
    monkeypatch.setenv("DM_TRACE", "1")
    with trace.span("SQL", "10 chars: SELECT 1") as info:
        info.update(rows=3, query_id="abc")
    out = capsys.readouterr().err.splitlines()
    assert "-> 10 chars: SELECT 1" in out[0]
    assert "<- ok" in out[1] and "rows=3" in out[1] and "query_id=abc" in out[1] and " ms " in out[1]


def test_failure_line_names_the_error(monkeypatch, capsys):
    monkeypatch.setenv("DM_TRACE", "1")
    with pytest.raises(ValueError):
        with trace.span("GEMMA", "call"):
            raise ValueError("boom")
    err = capsys.readouterr().err
    assert "FAILED" in err and "ValueError: boom" in err


def test_short_collapses_whitespace_and_notes_true_length():
    text = "SELECT   a,\n   b FROM t " + "x" * 300
    out = trace.short(text, 40)
    assert "\n" not in out and "  " not in out and out.endswith("chars)") and "(+" in out
    assert trace.short("SELECT 1") == "SELECT 1"


def test_http_hooks_never_print_the_authorization_header(monkeypatch, capsys):
    monkeypatch.setenv("DM_TRACE", "1")
    hooks = trace.httpx_hooks("ollama")
    request = httpx.Request("POST", "https://ollama.com/api/chat", headers={"Authorization": "Bearer sekret123"}, content=b"{}")
    hooks["request"][0](request)
    hooks["response"][0](httpx.Response(200, request=request, content=b"ok"))
    out = capsys.readouterr().err
    assert "sekret123" not in out and "Bearer" not in out
    assert "POST https://ollama.com/api/chat" in out and "HTTP 200" in out


def test_http_hooks_are_empty_when_tracing_is_off(monkeypatch):
    monkeypatch.delenv("DM_TRACE", raising=False)
    assert trace.httpx_hooks("ollama") == {}


def test_network_handler_turns_connector_log_lines_into_net_lines(monkeypatch, capsys):
    import logging
    monkeypatch.setenv("DM_TRACE", "1")
    handler = trace._NetHandler()
    for message in ("outbound HTTP call method=POST path=/queries/v1/query-request attempt=1",
                    "Received HTTP response response_len=4674",
                    "Sync query response received elapsed_ms=198.8 request_id=x query_id=y",
                    "outbound HTTP call method=GET path=https://stage.s3.amazonaws.com/results/a/data_0?X-Amz-Signature=SECRET attempt=1"):
        handler.emit(logging.LogRecord("snowflake.connector._core", logging.DEBUG, "f", 1, message, None, None))
    out = capsys.readouterr().err
    assert "POST /queries/v1/query-request" in out and "4,674 bytes" in out and "199 ms" in out
    assert "SECRET" not in out and "X-Amz-Signature" not in out
