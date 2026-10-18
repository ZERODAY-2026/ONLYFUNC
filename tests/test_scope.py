"""Data-source selector: sirf chune hue datasets prompt me jaate hain aur validator bhi sirf unhi ko allow karta hai (offline, fakes ke saath)."""
import pytest

from datamind import agent as agent_mod
from datamind import catalog
from datamind.config import load_config
from datamind.snowflake_client import QueryResult
from datamind.validator import ValidationError, validate

TPCH = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS"
WINE = "UCI.PUBLIC.WINE_QUALITY"


@pytest.fixture
def agent(monkeypatch):
    seen = []
    monkeypatch.setattr(agent_mod, "describe_schema", lambda conn, cfg: seen.append([d.name for d in cfg.datasets]) or "schema")
    return agent_mod.Agent(None, load_config()), seen


def test_subset_keeps_only_the_named_datasets_and_their_tables():
    cfg = load_config()
    wine = cfg.subset(["wine_quality"])
    assert [d.name for d in wine.datasets] == ["wine_quality"]
    assert wine.allowed_tables() == {("UCI", "PUBLIC", "WINE_QUALITY")}
    assert wine.max_rows == cfg.max_rows
    assert len(cfg.datasets) > 1                      # original Config bachi rehti hai


def test_validator_follows_the_subset():
    wine = load_config().subset(["wine_quality"])
    assert validate(f"SELECT COUNT(*) FROM {WINE}", wine).tables == [WINE]
    with pytest.raises(ValidationError):              # TPC-H switched off
        validate(f"SELECT COUNT(*) FROM {TPCH}", wine)


def test_default_scope_is_everything_and_adds_no_note(agent):
    ag, seen = agent
    assert ag.scope is None and ag.cfg is ag.full_cfg
    assert "switched off" not in ag.system


def test_set_scope_narrows_prompt_validator_and_adds_a_note(agent):
    ag, seen = agent
    ag.set_scope(["wine_quality", "owid"])
    assert ag.scope == ["wine_quality", "owid"]
    assert seen[-1] == ["wine_quality", "owid"]
    assert "Datasets enabled for this conversation: wine_quality, owid" in ag.system
    assert "tpch" in ag.system.split("switched off")[0]       # off list me tpch hai
    assert ("SNOWFLAKE_SAMPLE_DATA", "TPCH_SF1", "ORDERS") not in ag.cfg.allowed_tables()
    assert ag.full_cfg.allowed_tables() >= ag.cfg.allowed_tables()


def test_selecting_everything_again_clears_the_scope(agent):
    ag, _ = agent
    ag.set_scope(["wine_quality"])
    ag.set_scope([d.name for d in ag.full_cfg.datasets])
    assert ag.scope is None and ag.cfg is ag.full_cfg and "switched off" not in ag.system


def test_empty_or_unknown_selection_is_rejected_and_changes_nothing(agent):
    ag, _ = agent
    with pytest.raises(ValueError):
        ag.set_scope([])
    with pytest.raises(ValueError):
        ag.set_scope(["wine_quality", "no_such_dataset"])
    assert ag.scope is None and ag.cfg is ag.full_cfg


def test_dataset_status_reports_live_tables_with_counts_and_one_query_per_database(monkeypatch):
    calls = []

    def fake_run_query(conn, sql):
        calls.append(sql)
        if "SNOWFLAKE_SAMPLE_DATA" in sql:
            rows = [("TPCH_SF1", "ORDERS", 1500000, 9), ("TPCH_SF1", "CUSTOMER", 150000, 8), ("TPCDS_SF10TCL", "ITEM", 402000, 22)]
        else:
            rows = [("PUBLIC", "WINE_QUALITY", 6497, 14)]
        return QueryResult(["S", "T", "R", "C"], rows, "q")

    monkeypatch.setattr(catalog, "run_query", fake_run_query)
    cfg = load_config().subset(["tpch", "tpcds", "wine_quality", "bank_marketing"])
    status = catalog.dataset_status(None, cfg)
    assert status["wine_quality"] == {"present": 1, "total": 1, "missing": [], "tables": {"WINE_QUALITY": {"rows": 6497, "columns": 14}}}
    assert status["bank_marketing"]["present"] == 0 and status["bank_marketing"]["missing"] == ["BANK_MARKETING"] and status["bank_marketing"]["tables"] == {}
    assert status["tpch"]["present"] == 2 and status["tpch"]["total"] == 8 and "LINEITEM" in status["tpch"]["missing"]
    assert status["tpch"]["tables"]["ORDERS"] == {"rows": 1500000, "columns": 9}
    assert status["tpcds"]["present"] == 1 and status["tpcds"]["tables"]["ITEM"]["columns"] == 22
    assert len(calls) == 2                                    # SNOWFLAKE_SAMPLE_DATA ek baar, UCI ek baar


def test_dataset_status_keeps_a_missing_row_count_as_none(monkeypatch):
    monkeypatch.setattr(catalog, "run_query", lambda conn, sql: QueryResult(["S", "T", "R", "C"], [("PUBLIC", "WINE_QUALITY", None, 14)], "q"))
    status = catalog.dataset_status(None, load_config().subset(["wine_quality"]))
    assert status["wine_quality"]["tables"]["WINE_QUALITY"] == {"rows": None, "columns": 14}
