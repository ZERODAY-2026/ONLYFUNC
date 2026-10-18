"""Answer ki result rows ko ground-truth rows se compare karta hai. Pure functions, Snowflake ya model ki zarurat nahi."""
from datetime import date, datetime
from decimal import Decimal

REL_TOL = 1e-6
ABS_TOL = 0.01  # answer me ROUND(x, 2) chalega


def norm(v):
    """Snowflake values ko comparable banata hai: numbers -> float, dates -> ISO text, text -> trim karke lowercase."""
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
    """Truth row ki har value answer row ke alag cell me milti hai (answer me extra columns chalte hain)."""
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
    """(ok, reason) lautata hai. mode: scalar | rows | contains."""
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
