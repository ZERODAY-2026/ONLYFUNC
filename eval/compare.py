"""Compares an answer's result rows with the ground-truth rows. Pure functions, no Snowflake or model needed."""
from datetime import date, datetime
from decimal import Decimal

REL_TOL = 1e-6
ABS_TOL = 0.01  # accepts ROUND(x, 2) in the answer


def norm(v):
    """Make Snowflake values comparable: numbers -> float, dates -> ISO text, text -> trimmed lowercase."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v).strip().lower()


def close(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))
    return a == b


def row_covers(truth_row, answer_row) -> bool:
    """Every value of the truth row appears in a distinct cell of the answer row (extra answer columns are fine)."""
    remaining = [norm(c) for c in answer_row]
    for value in map(norm, truth_row):
        for i, cell in enumerate(remaining):
            if close(value, cell):
                del remaining[i]
                break
        else:
            return False
    return True


def match(truth_rows, answer_rows, mode: str = "rows", ordered: bool = False) -> tuple[bool, str]:
    """Returns (ok, reason). mode: scalar | rows | contains."""
    if mode == "scalar":
        if len(truth_rows) != 1 or len(truth_rows[0]) != 1:
            return False, "truth for a scalar case must be exactly one value"
        if len(answer_rows) != 1:
            return False, f"expected one row, got {len(answer_rows)}"
        if row_covers(truth_rows[0], answer_rows[0]):
            return True, ""
        return False, f"expected {truth_rows[0][0]!r}, got {list(answer_rows[0])!r}"

    if mode == "rows" and len(answer_rows) != len(truth_rows):
        return False, f"expected {len(truth_rows)} rows, got {len(answer_rows)}"
    if len(answer_rows) < len(truth_rows):
        return False, f"expected at least {len(truth_rows)} rows, got {len(answer_rows)}"

    if ordered:
        for i, t in enumerate(truth_rows):
            if not row_covers(t, answer_rows[i]):
                return False, f"row {i + 1}: expected {list(t)!r}, got {list(answer_rows[i])!r}"
        return True, ""

    unused = list(range(len(answer_rows)))
    for t in truth_rows:
        for i in unused:
            if row_covers(t, answer_rows[i]):
                unused.remove(i)
                break
        else:
            return False, f"no answer row matches the expected row {list(t)!r}"
    return True, ""
