"""Cost aur reliability: ab tak ke jawabon ki trace lines se latency, failures, Gemma aur Snowflake ka kaam, aur warehouse credits ka ek
andaza (estimate). Sirf wahi gina jaata hai jo code ne sach me record kiya (Answer.trace); koi number naya nahi banta.

Dhyan: yeh Snowflake ka billing nahi hai. Asli credits SNOWFLAKE.ACCOUNT_USAGE me hote hain (admin privilege chahiye aur kuch ghante ki der se
aate hain). Yahan sirf queries ke chalne ke time ko warehouse ke rate se multiply karte hain, isliye asli kharch isse zyada hota hai (idle time
aur har resume par 60 second ka minimum bhi bill hota hai).
"""
import os
import re
from collections import Counter
from statistics import median

_OK_MS = re.compile(r"<- ok (\d+) ms")
_QUERY_ID = re.compile(r"query_id=(\S+)")

# warehouse size -> credits per hour (Snowflake ki standard table)
WAREHOUSE_RATES = {"XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8, "XLARGE": 16}


def credits_per_hour() -> float:
    """DM_WAREHOUSE_CREDITS_PER_HOUR (default 1 = XSMALL, jo setup.sql banata hai)."""
    try:
        return max(float(os.getenv("DM_WAREHOUSE_CREDITS_PER_HOUR", "1")), 0.0)
    except ValueError:
        return 1.0


def credit_budget() -> float | None:
    """DM_CREDIT_BUDGET (credits me, optional): estimate iske paas pahunche toh UI chetavni deti hai."""
    try:
        value = float(os.getenv("DM_CREDIT_BUDGET", ""))
        return value if value > 0 else None
    except ValueError:
        return None


def summarize(answers) -> dict:
    """Answers (har ek ki .trace aur .status) se session ka hisaab. Jin answers me trace nahi (purane saved chats) unhe 'untraced' gina jaata hai."""
    status = Counter(a.status for a in answers)
    out = {"questions": len(answers), "status": dict(status), "traced": 0, "untraced": 0, "latency_ms": [],
           "gemma_calls": 0, "gemma_ms": 0, "gemma_failures": 0, "statements": 0, "statement_ms": 0,
           "snowflake_rejections": 0, "validator_rejections": 0, "retries": 0, "slowest": []}
    for a in answers:
        lines = a.trace or []
        if not lines:
            out["untraced"] += 1
            continue
        out["traced"] += 1
        out["latency_ms"].append(lines[-1]["ms"])
        for line in lines:
            tag, msg = line["tag"], line["message"]
            took = _OK_MS.search(msg)
            if tag == "GEMMA":
                if took:
                    out["gemma_calls"] += 1
                    out["gemma_ms"] += int(took.group(1))
                elif msg.startswith("<- FAILED"):
                    out["gemma_failures"] += 1
            elif tag == "SQL":
                if took:
                    ms = int(took.group(1))
                    qid = _QUERY_ID.search(msg)
                    out["statements"] += 1
                    out["statement_ms"] += ms
                    out["slowest"].append({"ms": ms, "question": a.question, "query_id": qid.group(1) if qid else ""})
                elif "Snowflake rejected the query" in msg:
                    out["snowflake_rejections"] += 1
            elif tag == "VALIDATE" and msg.startswith("REJECTED"):
                out["validator_rejections"] += 1
            elif tag == "PLAN" and msg.startswith("attempt 2"):
                out["retries"] += 1
    lat = out["latency_ms"]
    out["median_ms"] = int(median(lat)) if lat else 0
    out["max_ms"] = max(lat) if lat else 0
    out["slowest"] = sorted(out["slowest"], key=lambda s: -s["ms"])[:3]
    rate = credits_per_hour()
    out["estimated_credits"] = out["statement_ms"] / 1000 / 3600 * rate
    budget = credit_budget()
    out["budget"] = budget
    out["budget_used"] = (out["estimated_credits"] / budget) if budget else None
    out["errors"] = status.get("error", 0)
    return out
