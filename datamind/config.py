"""Loads datasets.yaml and environment settings."""
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
# The Snowflake connector prints a long FutureWarning about a keep-alive default on every login; it is harmless here.
warnings.filterwarnings("ignore", message=".*enable_server_session_keep_alive.*", category=FutureWarning)

Table = tuple[str, str, str]            # (DATABASE, SCHEMA, TABLE), uppercase
Column = tuple[str, str, str, str]      # (DATABASE, SCHEMA, TABLE, COLUMN), uppercase


@dataclass
class Dataset:
    name: str
    description: str
    database: str
    schema: str
    tables: list[str]
    source: str = ""
    licence: str = ""
    load: dict = field(default_factory=dict)
    # Optional semantic catalogue (see datasets.yaml)
    scope: str = ""
    metrics: dict[str, str] = field(default_factory=dict)
    joins: list[str] = field(default_factory=list)
    columns: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)

    def qualified(self, table: str) -> Table:
        return (self.database.upper(), self.schema.upper(), table.upper())

    def join_pairs(self) -> set[frozenset[Column]]:
        pairs = set()
        for rule in self.joins:
            left, right = (side.strip().upper().split(".") for side in rule.split("="))
            pairs.add(frozenset({self.qualified(left[0]) + (left[1],), self.qualified(right[0]) + (right[1],)}))
        return pairs


@dataclass
class Config:
    datasets: list[Dataset]
    max_rows: int = 200
    allowed_functions: list[str] = field(default_factory=list)  # extra SQL functions beyond the validator's defaults

    def allowed_tables(self) -> set[Table]:
        return {d.qualified(t) for d in self.datasets for t in d.tables}

    def join_rules(self) -> tuple[set[frozenset[Column]], set[Table]]:
        """(allowed join pairs, tables that are constrained). A table is constrained when its dataset declares joins."""
        pairs: set[frozenset[Column]] = set()
        constrained: set[Table] = set()
        for d in self.datasets:
            if d.joins:
                pairs |= d.join_pairs()
                constrained |= {d.qualified(t) for t in d.tables}
        return pairs, constrained


def load_config(path: Path | None = None) -> Config:
    raw = yaml.safe_load((path or ROOT / "datasets.yaml").read_text(encoding="utf-8"))
    return Config(
        datasets=[Dataset(**d) for d in raw["datasets"]],
        max_rows=int(raw.get("max_rows", 200)),
        allowed_functions=list(raw.get("allowed_functions", [])),
    )


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing environment variable {name}. Copy .env.example to .env and fill it in.")
    return value
