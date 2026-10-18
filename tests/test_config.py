from datamind.config import load_config
from datamind.ports import free_port


def test_datasets_yaml_loads():
    cfg = load_config()
    assert cfg.max_rows > 0
    assert {d.name for d in cfg.datasets} >= {"tpch", "wine_quality"}


def test_allowed_tables_are_fully_qualified_uppercase():
    allowed = load_config().allowed_tables()
    assert ("SNOWFLAKE_SAMPLE_DATA", "TPCH_SF1", "ORDERS") in allowed
    assert all(len(t) == 3 and all(p == p.upper() for p in t) for t in allowed)


def test_loadable_datasets_define_their_table():
    for d in load_config().datasets:
        if d.load:
            recipes = d.load if isinstance(d.load, list) else [d.load]
            assert {r["table"].upper() for r in recipes} == {t.upper() for t in d.tables}


def test_free_port_returns_a_bindable_port():
    port = free_port(8501)
    assert 8501 <= port < 8521
