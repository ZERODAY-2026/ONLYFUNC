"""Read-only SQL guardrail. Everything Gemma writes must pass this before Snowflake sees it.
Function and join allowlists adapted from the teammate AI-module handoff (MIT)."""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from .config import Config, Table

FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
    exp.Alter, exp.Command, exp.Copy, exp.TruncateTable, exp.Use, exp.Set,
)

# Functions a data question reasonably needs. Anything else (SYSTEM$..., GET_DDL, UDFs, CURRENT_*) is refused.
# Extend per project with `allowed_functions:` in datasets.yaml.
DEFAULT_FUNCTIONS = {
    "SUM", "COUNT", "AVG", "MIN", "MAX", "MEDIAN", "STDDEV", "STDDEV_POP", "STDDEV_SAMP", "VARIANCE", "CORR",
    "ROUND", "FLOOR", "CEIL", "ABS", "COALESCE", "NULLIF", "IFNULL", "NVL", "IFF", "IF", "CASE", "CAST", "TRY_CAST",
    # sqlglot reports Snowflake's DATE_TRUNC as TIMESTAMP_TRUNC, DATEADD as DATE_ADD and TO_DATE as TS_OR_DS_TO_DATE
    "YEAR", "MONTH", "DAY", "QUARTER", "DATE_TRUNC", "TIMESTAMP_TRUNC", "EXTRACT", "DATEADD", "DATE_ADD",
    "DATEDIFF", "DATE_DIFF", "TO_DATE", "TS_OR_DS_TO_DATE",
    "LOWER", "UPPER", "TRIM", "LENGTH", "SUBSTR", "SUBSTRING", "CONCAT",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "COUNT_IF",
}


class ValidationError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable  # True: a slip Gemma can fix; False: refuse outright


@dataclass
class Validated:
    sql: str
    tables: list[str]  # fully qualified tables the query reads


def validate(sql: str, cfg: Config, max_rows: int | None = None) -> Validated:
    max_rows = max_rows or cfg.max_rows
    allowed = cfg.allowed_tables()
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        raise ValidationError("Empty SQL.", retryable=True)
    try:
        statements = [s for s in sqlglot.parse(sql, read="snowflake") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise ValidationError(f"SQL could not be parsed: {e}", retryable=True)
    if len(statements) != 1:
        raise ValidationError("Only a single statement is allowed.")
    tree = statements[0]
    if tree.find(*FORBIDDEN) or not isinstance(tree, exp.Query):
        raise ValidationError("Only read-only SELECT queries are allowed.")

    cte_names = {c.alias_or_name.upper() for c in tree.find_all(exp.CTE)}
    used: list[str] = []
    alias_map: dict[str, Table] = {}
    for t in tree.find_all(exp.Table):
        if not t.name or t.name.upper() in cte_names and not t.db:
            continue
        if not (t.db and t.catalog):
            raise ValidationError(
                f"Table {t.name} must be fully qualified as DATABASE.SCHEMA.TABLE.", retryable=True)
        key: Table = (t.catalog.upper(), t.db.upper(), t.name.upper())
        if key not in allowed:
            raise ValidationError(f"Table {'.'.join(key)} is not part of the configured datasets.")
        used.append(".".join(key))
        alias_map[t.alias_or_name.upper()] = key
    if not used:
        raise ValidationError("The query does not read from any configured table.", retryable=True)

    permitted = DEFAULT_FUNCTIONS | {f.upper() for f in cfg.allowed_functions}
    for fn in tree.find_all(exp.Func):
        if isinstance(fn, (exp.And, exp.Or, exp.Not)):
            continue
        if fn.sql_name().upper() not in permitted:
            name = fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()  # unknown functions are "ANONYMOUS"
            raise ValidationError(f"Function {name} is not allowed.", retryable=True)

    opaque = cte_names | {s.alias.upper() for s in tree.find_all(exp.Subquery) if s.alias}
    # `FROM some_cte AS c`: the alias c also names a CTE, so its columns cannot be traced to a base table here either.
    opaque |= {t.alias.upper() for t in tree.find_all(exp.Table) if t.alias and not t.db and t.name.upper() in cte_names}
    _check_joins(tree, alias_map, opaque, cfg)

    if tree.args.get("limit") is None:
        tree = exp.select("*").from_(tree.subquery("q")).limit(max_rows)
    return Validated(sql=tree.sql(dialect="snowflake"), tables=sorted(set(used)))


def _check_joins(tree: exp.Expression, alias_map: dict[str, Table], opaque: set[str], cfg: Config) -> None:
    """Joins must have an ON condition; equalities touching a dataset that declares joins must be approved ones.
    Columns of a CTE or derived table (`opaque`) cannot be traced to a base table here; the base tables inside
    them are validated on their own."""
    pairs, constrained = cfg.join_rules()
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            raise ValidationError("Every JOIN needs an explicit ON condition.", retryable=True)
        column_equalities = [c for c in on.find_all(exp.EQ)
                             if isinstance(c.left, exp.Column) and isinstance(c.right, exp.Column)]
        if not column_equalities:
            raise ValidationError("A JOIN must compare key columns of the two tables.", retryable=True)
        for cond in column_equalities:
            if any(c.table and c.table.upper() in opaque for c in (cond.left, cond.right)):
                continue  # touches a CTE/derived table; cannot be traced to a base column here
            sides = []
            for col in (cond.left, cond.right):
                table = alias_map.get(col.table.upper()) if col.table else None
                if table is None:
                    raise ValidationError("Qualify JOIN columns with the table alias.", retryable=True)
                sides.append(table + (col.name.upper(),))
            if any(s[:3] in constrained for s in sides) and frozenset(sides) not in pairs:
                raise ValidationError(
                    f"JOIN {cond.sql()} is not an approved relationship; use the allowed joins.", retryable=True)
