"""`tables: auto`: tables Snowflake se aati hain, datasets.yaml se nahi (offline, fake Snowflake ke saath)."""
import pytest

from datamind import catalog
from datamind.config import Config, Dataset, load_config
from datamind.snowflake_client import QueryResult
from datamind.validator import ValidationError, validate

D = "DATAMIND.PUBLIC"


def make_cfg() -> Config:
    explicit = Dataset(name="known", description="x", database="DATAMIND", schema="PUBLIC", tables=["KNOWN_A"])
    auto = Dataset(name="rest", description="y", database="DATAMIND", schema="PUBLIC", tables="auto")
    return Config(datasets=[explicit, auto])


def fake_schema(monkeypatch, tables: list[str]):
    seen = []

    def fake_run_query(conn, sql):
        seen.append(sql)
        if "INFORMATION_SCHEMA.COLUMNS" in sql:  # describe_schema: jo table maangi jaaye uska ek column
            asked = [t for t in tables if f"'{t}'" in sql]
            return QueryResult(columns=["T", "C", "D", "N"], rows=[(t, "ID", "NUMBER", 1234) for t in asked], query_id="q")
        return QueryResult(columns=["TABLE_NAME"], rows=[(t,) for t in tables], query_id="q")

    monkeypatch.setattr(catalog, "run_query", fake_run_query)
    return seen


def test_auto_word_parses_to_an_empty_discoverable_dataset():
    d = Dataset(name="n", description="d", database="DB", schema="S", tables="AUTO")
    assert d.auto and d.tables == []


def test_a_wrong_tables_word_is_rejected():
    with pytest.raises(ValueError):
        Dataset(name="n", description="d", database="DB", schema="S", tables="everything")


def test_real_config_lists_its_datasets_explicitly():
    cfg = load_config()
    assert not any(d.auto for d in cfg.datasets)      # auto discovery available hai par on nahi hai
    assert {d.name for d in cfg.datasets} >= {"tpch", "wine_quality", "owid", "bank_marketing", "student_performance"}
    assert ("UCI", "PUBLIC", "WINE_QUALITY") in cfg.allowed_tables()


def test_discovery_adds_new_tables_and_leaves_listed_ones_to_their_dataset(monkeypatch):
    cfg = make_cfg()
    seen = fake_schema(monkeypatch, ["KNOWN_A", "NEW_B", "NEW_C"])
    catalog.discover_tables(None, cfg)
    assert cfg.datasets[1].tables == ["NEW_B", "NEW_C"]
    assert cfg.datasets[0].tables == ["KNOWN_A"]
    assert "DATAMIND.INFORMATION_SCHEMA.TABLES" in seen[0] and "'PUBLIC'" in seen[0]


def test_discovery_is_refreshable_new_appear_dropped_vanish(monkeypatch):
    cfg = make_cfg()
    fake_schema(monkeypatch, ["NEW_B"])
    catalog.discover_tables(None, cfg)
    fake_schema(monkeypatch, ["NEW_C"])
    catalog.discover_tables(None, cfg)
    assert cfg.datasets[1].tables == ["NEW_C"]


def test_validator_allowlist_follows_discovery(monkeypatch):
    cfg = make_cfg()
    sql = f"SELECT COUNT(*) FROM {D}.NEW_B"
    with pytest.raises(ValidationError):      # discovery se pehle unknown
        validate(sql, cfg)
    fake_schema(monkeypatch, ["NEW_B"])
    catalog.discover_tables(None, cfg)
    assert validate(sql, cfg).tables == [f"{D}.NEW_B"]
    fake_schema(monkeypatch, [])              # table drop hui, phir re-scan
    catalog.discover_tables(None, cfg)
    with pytest.raises(ValidationError):
        validate(sql, cfg)


def test_describe_schema_labels_auto_tables_and_skips_an_empty_auto_dataset(monkeypatch):
    cfg = make_cfg()
    fake_schema(monkeypatch, ["KNOWN_A"])     # kuch naya nahi: auto dataset koi heading nahi jodta
    assert "Dataset 'rest'" not in catalog.describe_schema(None, cfg)
    fake_schema(monkeypatch, ["KNOWN_A", "NEW_B"])
    text = catalog.describe_schema(None, cfg)
    assert "Dataset 'rest'" in text and "discovered automatically" in text
