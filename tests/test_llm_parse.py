from datamind.llm import parse_json


def test_plain_json():
    assert parse_json('{"action": "query", "sql": "SELECT 1"}')["action"] == "query"


def test_fenced_json():
    assert parse_json('```json\n{"action": "clarify", "message": "which year?"}\n```')["action"] == "clarify"


def test_prose_around_json():
    assert parse_json('Here you go: {"action": "query", "sql": "SELECT 1"} Hope it helps.')["sql"] == "SELECT 1"


def test_garbage_is_unsupported():
    assert parse_json("no json here")["action"] == "unsupported"
