"""Check karta hai ki model ke likhe explanation me sirf wahi numbers hain jo evidence me sach me hain.
Idea teammate ke AI-module handoff (MIT) se liya hai, aur thousands separators aur rounding ke liye badhaya hai."""
import re

# Number kisi word character par ya ",digit"/".digit" par khatam hota hai (toh "7,012,696.48." ek hi number hai, "7,012" nahi).
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?!\w|[.,]\d)")


def _numbers(text: str) -> list[tuple[float, int]]:
    """Text ke har number ke liye (value, decimal places); thousands separators ignore hote hain."""
    out = []
    for token in _NUM.findall(text):
        clean = token.replace(",", "")
        try:
            out.append((float(clean), len(clean.split(".")[1]) if "." in clean else 0))
        except ValueError:
            continue
    return out


def numbers_grounded(explanation: str, question: str, sql: str, assumptions: list[str], rows: list[tuple]) -> bool:
    """True agar explanation ka har number question, SQL, assumptions ya rows me hai
    (explanation kisi row value ko round kar sakta hai, jaise 10.5876 -> 10.59, ya list ko 1..n number de sakta hai)."""
    evidence = [question, sql, " ".join(assumptions)]
    for row in rows:
        evidence.extend(str(cell) for cell in row)
    allowed = {value for text in evidence for value, _ in _numbers(text)}
    allowed |= {float(n) for n in range(0, len(rows) + 1)}  # row count aur list numbering
    for value, places in _numbers(explanation):
        if not any(abs(round(a, places) - value) < 1e-9 for a in allowed):
            return False
    return True


def evidence_fallback(columns: list[str], rows: list[tuple]) -> str:
    """Pehli row se bana exact-value jawab, jab model ke text ko verify nahi kiya ja sakta."""
    first = ", ".join(f"{c}: {v}" for c, v in zip(columns, rows[0]))
    if len(rows) > 1:
        return f"The answer is shown in the Snowflake result rows. Snowflake returned {len(rows)} result rows; the first row is {first}."
    return f"The answer is shown in the Snowflake result rows. Snowflake returned: {first}."
