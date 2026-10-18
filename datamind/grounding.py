"""Checks that a model-written explanation only states numbers that really appear in the evidence.
Idea adapted from the teammate AI-module handoff (MIT), extended for thousands separators and rounding."""
import re

# A number ends at a word character or at ",digit"/".digit" (so "7,012,696.48." is one number, not "7,012").
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?!\w|[.,]\d)")


def _numbers(text: str) -> list[tuple[float, int]]:
    """(value, decimal places) for every number in the text; thousands separators are ignored."""
    out = []
    for token in _NUM.findall(text):
        clean = token.replace(",", "")
        try:
            out.append((float(clean), len(clean.split(".")[1]) if "." in clean else 0))
        except ValueError:
            continue
    return out


def numbers_grounded(explanation: str, question: str, sql: str, assumptions: list[str], rows: list[tuple]) -> bool:
    """True if every number in the explanation is in the question, SQL, assumptions or rows
    (an explanation may round a row value, e.g. 10.5876 -> 10.59, or number a list 1..n)."""
    evidence = [question, sql, " ".join(assumptions)]
    for row in rows:
        evidence.extend(str(cell) for cell in row)
    allowed = {value for text in evidence for value, _ in _numbers(text)}
    allowed |= {float(n) for n in range(0, len(rows) + 1)}  # row count and list numbering
    for value, places in _numbers(explanation):
        if not any(abs(round(a, places) - value) < 1e-9 for a in allowed):
            return False
    return True


def evidence_fallback(columns: list[str], rows: list[tuple]) -> str:
    """Exact-value answer built from the first row, used when the model's prose cannot be verified."""
    first = ", ".join(f"{c}: {v}" for c, v in zip(columns, rows[0]))
    if len(rows) > 1:
        return f"The answer is shown in the Snowflake result rows. Snowflake returned {len(rows)} result rows; the first row is {first}."
    return f"The answer is shown in the Snowflake result rows. Snowflake returned: {first}."
