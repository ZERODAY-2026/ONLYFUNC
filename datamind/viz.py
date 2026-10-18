"""Visualisation: Snowflake se aayi result rows ko sahi chart me badalta hai.

Yahan Gemma kuch nahi karta aur koi number naya nahi banta: chart ka type rows ki shakal (kaunse columns number, saal/tarikh ya label hain)
aur sawal ke shabdon se tay hota hai, aur chart sirf wahi rows dikhata hai jo Snowflake ne lautayi. Streamlit ka koi code yahan nahi hai,
isliye yeh poora module offline test ho jaata hai.
"""
import re
from dataclasses import dataclass, field

import altair as alt
import pandas as pd

BRAND = "#d91528"          # app ka lal rang
MAX_BARS = 30              # bar chart me zyada se zyada itni bars
MAX_SERIES = 8             # rang se alag ki jaane wali series ki limit
MAX_PIE = 8                # donut me itne hisse tak hi padhne layak rehta hai

# column ke naam se pehchaan: saal/mahina waghera ek order wali cheez hai, ID/KEY wale columns ginti nahi, label hain
_TIME_NAME = re.compile(r"(^|_)(year|yr|month|quarter|week|date|day|period)s?($|_)", re.I)
_ID_NAME = re.compile(r"(^|_)(id|key|sk)$|key$", re.I)
_DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}")

# sawal ke shabd -> kaun sa chart default ho (sirf tab jab woh chart us data ke liye possible ho)
_HINTS = [
    ("line", re.compile(r"\b(trend|over time|since|per year|by year|each year|yearly|monthly|per month|by month|history|changed?|growth|evolution|timeline)\b", re.I)),
    ("donut", re.compile(r"\b(share|percent(age)?|proportion|breakdown|split|composition|make[s]? up|out of)\b", re.I)),
    ("histogram", re.compile(r"\b(distribution|spread|histogram|range of|how are .* distributed)\b", re.I)),
    ("scatter", re.compile(r"\b(relationship|correlat\w*|versus|vs\.?|against|related)\b", re.I)),
]

TYPE_LABELS = {"metric": "Number", "bar": "Bar", "line": "Line", "scatter": "Scatter", "histogram": "Histogram", "donut": "Donut"}


@dataclass
class Plan:
    kinds: dict[str, str]                 # column -> numeric | temporal | category
    types: list[str]                      # possible chart types, best first
    default: str
    x: str | None = None                  # label ya time column
    x_options: list[str] = field(default_factory=list)   # X axis ke liye chune ja sakne wale columns
    y_options: list[str] = field(default_factory=list)   # number columns jo chunne ke liye hain
    series: str | None = None             # rang se alag karne wala category column
    reason: str = ""


@dataclass
class Built:
    chart: alt.Chart
    note: str = ""


def _unique_names(columns) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in columns:
        seen[c] = seen.get(c, 0) + 1
        out.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    return out


def _kind_and_values(name: str, s: pd.Series) -> tuple[str, pd.Series]:
    """(kind, series). Saved chats me Decimal/date text ban jaate hain, isliye text ko wapas number/tarikh me badalte hain."""
    if pd.api.types.is_bool_dtype(s):
        return "category", s.astype(str)
    if pd.api.types.is_datetime64_any_dtype(s):
        return "temporal", s
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        present = s.dropna()
        if present.empty:
            return "category", s
        nums = pd.to_numeric(s, errors="coerce")
        if nums.notna().sum() >= 0.95 * len(present) and not _ID_NAME.search(name):
            s = nums
        else:
            if present.astype(str).str.match(_DATE_TEXT).all():
                parsed = pd.to_datetime(s, errors="coerce")
                if parsed.notna().sum() == len(present):
                    return "temporal", parsed
            return "category", s.astype(str)
    s = pd.to_numeric(s, errors="coerce") if not pd.api.types.is_numeric_dtype(s) else s
    present = s.dropna()
    if present.empty:
        return "category", s.astype(str)
    if _TIME_NAME.search(name) and (present % 1 == 0).all() and present.max() <= 2200:
        return "temporal", s
    if _ID_NAME.search(name):
        return "category", s.astype(str)
    return "numeric", s


def to_frame(columns, rows) -> pd.DataFrame:
    """Rows ko typed DataFrame banata hai; har column ka kind frame.attrs['kinds'] me."""
    names = _unique_names(list(columns))
    raw = pd.DataFrame([list(r) for r in rows], columns=names)
    out, kinds = pd.DataFrame(index=raw.index), {}
    for name in names:
        kinds[name], out[name] = _kind_and_values(name, raw[name])
    out.attrs["kinds"] = kinds
    return out


def suggest(frame: pd.DataFrame, question: str = "") -> Plan | None:
    """Data ki shakal aur sawal ke shabdon se chart plan; None agar kuch bhi aisa nahi jo achhe se chart ho (jaise sirf text)."""
    kinds = frame.attrs.get("kinds") or {c: "category" for c in frame.columns}
    n = len(frame)
    numerics = [c for c in frame.columns if kinds[c] == "numeric"]
    temporals = [c for c in frame.columns if kinds[c] == "temporal"]
    cats = [c for c in frame.columns if kinds[c] == "category"]
    if n == 0 or not numerics:
        return None
    if n == 1:
        return Plan(kinds, ["metric"], "metric", cats[0] if cats else None, [], numerics,
                    reason="The result is a single row, so the numbers are shown as they are.")

    # score/rating jaisa chhote poore numbers wala column (jaise QUALITY 3..8) plot karne ki cheez nahi, axis hai
    ordinal = [c for c in numerics if frame[c].nunique() <= 12 and (frame[c].dropna() % 1 == 0).all()] if len(numerics) >= 2 else []
    if ordinal and not temporals:
        cats = [ordinal[0]] + cats
        numerics = [c for c in numerics if c != ordinal[0]]
    x_options = [c for c in temporals + cats]
    x, series, types = None, None, []
    if temporals:
        x = temporals[0]
        types = ["line", "bar"]
        group = [c for c in cats if 2 <= frame[c].nunique() <= MAX_SERIES]
        series = group[0] if group else None
        reason = f"{x} is a time column and {numerics[0]} is a number, so a line shows how it changes."
    elif cats:
        label = next((c for c in cats if frame[c].nunique() >= 2), cats[0])
        x = label
        others = [c for c in cats if c != label and kinds[c] == "category" and 2 <= frame[c].nunique() <= MAX_SERIES]
        series = others[0] if others else None
        types = ["bar"]
        if series is None and 2 <= n <= MAX_PIE and frame[label].nunique() == n and (frame[numerics[0]].dropna() >= 0).all():
            types.append("donut")
        reason = f"{label} is a label and {numerics[0]} is a number, so bars compare them."
    if len(numerics) >= 2:
        types.append("scatter")
        if not types[:-1]:
            x = numerics[0]
            reason = f"There are two number columns ({numerics[0]} and {numerics[1]}), so a scatter shows how they relate."
    if n >= 8:
        types.append("histogram")
        if not types[:-1]:
            reason = f"{numerics[0]} has {n} values, so a histogram shows how they are spread."
    if not types:
        return None

    default = types[0]
    hinted = ""
    for chart_type, pattern in _HINTS:
        if chart_type in types and pattern.search(question or ""):
            default, hinted = chart_type, f" Your question's wording points to a {TYPE_LABELS[chart_type].lower()} chart."
            break
    return Plan(kinds, types, default, x, x_options, numerics, series, reason + hinted)


def make_chart(frame: pd.DataFrame, plan: Plan, chart_type: str, y: str | None = None, x: str | None = None) -> Built | None:
    """Plan aur chart type se Altair chart. Columns ke naam alag (c0, c1...) rakhte hain taaki AVG(ALCOHOL) jaise naam encoding na bigaden."""
    if chart_type not in plan.types or chart_type == "metric":
        return None
    x = x if x in plan.x_options else plan.x
    y = y if y in plan.y_options and y != x else next((c for c in plan.y_options if c != x), None)
    if y is None:
        return None
    # chuna hua X number ho (jaise QUALITY) toh use label ki tarah treat karo; series wahi nahi ho sakti jo X hai
    xkind = "category" if plan.kinds.get(x) == "numeric" else plan.kinds.get(x)
    series = plan.series if plan.series != x else None
    safe = {c: f"c{i}" for i, c in enumerate(frame.columns)}
    data = frame.rename(columns=safe)
    tip = lambda col, kind: alt.Tooltip(safe[col], title=col, type=kind, **({"format": ",.2f"} if kind == "quantitative" else {}))
    note = ""

    if chart_type == "histogram":
        chart = alt.Chart(data).mark_bar(color=BRAND).encode(
            x=alt.X(safe[y], bin=alt.Bin(maxbins=20), type="quantitative", title=y),
            y=alt.Y("count()", title="Rows"))
    elif chart_type == "scatter":
        x_col = x if plan.kinds.get(x) == "numeric" and x != y else next((c for c in plan.y_options if c != y), None)
        if x_col is None:
            return None
        enc = dict(x=alt.X(safe[x_col], type="quantitative", title=x_col, scale=alt.Scale(zero=False)),
                   y=alt.Y(safe[y], type="quantitative", title=y, scale=alt.Scale(zero=False)),
                   tooltip=[tip(c, "quantitative") for c in dict.fromkeys([x_col, y])])
        if series:
            enc["color"] = alt.Color(safe[series], type="nominal", title=series)
        chart = alt.Chart(data).mark_circle(size=70, color=BRAND, opacity=0.75).encode(**enc)
    elif chart_type == "donut":
        chart = alt.Chart(data).mark_arc(innerRadius=70).encode(
            theta=alt.Theta(safe[y], type="quantitative", title=y),
            color=alt.Color(safe[x], type="nominal", title=x),
            tooltip=[tip(x, "nominal"), tip(y, "quantitative")])
    elif chart_type == "line":
        x_type = "temporal" if xkind == "temporal" and pd.api.types.is_datetime64_any_dtype(frame[x]) else "quantitative"
        x_enc = alt.X(safe[x], type=x_type, title=x, **({"axis": alt.Axis(format="d")} if x_type == "quantitative" else {}),
                      **({"scale": alt.Scale(zero=False)} if x_type == "quantitative" else {}))
        enc = dict(x=x_enc, y=alt.Y(safe[y], type="quantitative", title=y, scale=alt.Scale(zero=False)),  # trend line ka axis tight rakho
                   tooltip=[tip(x, x_type), tip(y, "quantitative")])
        if series:
            enc["color"] = alt.Color(safe[series], type="nominal", title=series)
            enc["tooltip"].append(tip(series, "nominal"))
        chart = alt.Chart(data.sort_values(safe[x])).mark_line(point=True, **({} if series else {"color": BRAND})).encode(**enc)
    else:  # bar
        use = data.dropna(subset=[safe[y]])
        if not series and xkind != "temporal":
            use = use.sort_values(safe[y], ascending=False)
        if len(use) > MAX_BARS:
            note = f"Showing the top {MAX_BARS} of {len(use)} rows."
            use = use.head(MAX_BARS)
        label_len = use[safe[x]].astype(str).str.len().max()
        horizontal = xkind != "temporal" and (len(use) > 8 or label_len > 14)
        x_type = "nominal" if xkind != "temporal" else "ordinal"
        cat = alt.X(safe[x], type=x_type, title=x, sort=None if x_type == "ordinal" or plan.kinds.get(x) == "numeric" else "-y")
        val = alt.Y(safe[y], type="quantitative", title=y)
        tooltips = [tip(x, x_type), tip(y, "quantitative")]
        if horizontal:
            enc = dict(y=alt.Y(safe[x], type=x_type, title=x, sort="-x"), x=alt.X(safe[y], type="quantitative", title=y), tooltip=tooltips)
        else:
            enc = dict(x=cat, y=val, tooltip=tooltips)
        if series:
            enc["color"] = alt.Color(safe[series], type="nominal", title=series)
            enc["tooltip"] = tooltips + [tip(series, "nominal")]
        chart = alt.Chart(use).mark_bar(**({} if series else {"color": BRAND})).encode(**enc)

    return Built(chart.properties(height=320).configure_view(strokeWidth=0).configure_axis(labelLimit=220), note)
