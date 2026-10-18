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
    suggestions: list[str] = field(default_factory=list)  # follow-up sawal jo user click karke pooch sakta hai
    trace: list[dict] = field(default_factory=list)       # is sawal ke dauran bani trace lines: {time, ms, tag, message}
    steps: list["Answer"] = field(default_factory=list)   # multipart sawal me har hissa ka apna jawab (alag dataset, alag SQL)

    def __post_init__(self):
        # saved chat se wapas aate waqt steps dict hote hain; unhe Answer bana do
        self.steps = [s if isinstance(s, Answer) else Answer(**s) for s in self.steps]
