"""Woh data shapes jo workflow aur UI dono use karte hain."""
from dataclasses import dataclass, field


@dataclass
class Answer:
    status: str  # status: answered | empty | clarify | unsupported | refused | error
    question: str
    message: str = ""
    sql: str = ""
    executed_sql: str = ""
    tables: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    query_id: str = ""
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)
