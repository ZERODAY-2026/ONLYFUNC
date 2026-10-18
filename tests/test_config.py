from datamind.config import load_config


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
            assert d.load["table"].upper() in {t.upper() for t in d.tables}
