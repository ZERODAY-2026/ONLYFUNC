import pytest

from datamind.config import load_config
from datamind.validator import ValidationError, validate

CFG = load_config()
T = "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1"
W = "DATAMIND.PUBLIC.WINE_QUALITY"


def ok(sql, max_rows=100):
    return validate(sql, CFG, max_rows)


def test_select_gets_limit():
    v = ok(f"SELECT COUNT(*) FROM {T}.ORDERS")
    assert "LIMIT 100" in v.sql.upper()
    assert v.tables == [f"{T}.ORDERS"]


def test_existing_limit_kept():
    v = ok(f"SELECT O_ORDERKEY FROM {T}.ORDERS LIMIT 5")
    assert "LIMIT 5" in v.sql.upper() and "LIMIT 100" not in v.sql.upper()


def test_cte_and_approved_join_ok():
    sql = (f"WITH c AS (SELECT C_CUSTKEY FROM {T}.CUSTOMER) "
           f"SELECT COUNT(*) FROM {T}.ORDERS o JOIN c ON o.O_CUSTKEY = c.C_CUSTKEY")
    # the CTE hides the real table from the join check, but the join itself is on approved key names
    assert len(ok(sql).tables) == 2


def test_aliased_cte_references_ok():
    """`FROM some_cte AS c` joins on columns of the CTE (found live: a before/after comparison of two CTEs)."""
    D = "DATAMIND.PUBLIC"
    sql = (f"WITH a AS (SELECT ENTITY, LIFE_EXPECTANCY FROM {D}.OWID_LIFE_EXPECTANCY WHERE YEAR = 1990), "
           f"b AS (SELECT ENTITY, LIFE_EXPECTANCY FROM {D}.OWID_LIFE_EXPECTANCY WHERE YEAR = 2020) "
           "SELECT b2.ENTITY, b2.LIFE_EXPECTANCY - a1.LIFE_EXPECTANCY AS GAIN FROM b AS b2 JOIN a AS a1 ON b2.ENTITY = a1.ENTITY")
    assert ok(sql).tables == [f"{D}.OWID_LIFE_EXPECTANCY".upper()]


@pytest.mark.parametrize("sql", [
    # queries the model has actually written, or the handoff's golden cases
    f"SELECT c.C_NAME, n.N_NAME, SUM(o.O_TOTALPRICE) AS T FROM {T}.CUSTOMER AS c JOIN {T}.ORDERS AS o ON c.C_CUSTKEY = o.O_CUSTKEY JOIN {T}.NATION AS n ON c.C_NATIONKEY = n.N_NATIONKEY GROUP BY c.C_NAME, n.N_NAME ORDER BY T DESC LIMIT 5",
    f"SELECT r.R_NAME, COUNT(c.C_CUSTKEY) FROM {T}.REGION r JOIN {T}.NATION n ON r.R_REGIONKEY = n.N_REGIONKEY JOIN {T}.CUSTOMER c ON n.N_NATIONKEY = c.C_NATIONKEY GROUP BY r.R_NAME",
    f"SELECT QUALITY, AVG(ALCOHOL) FROM {W} GROUP BY QUALITY",
    f"SELECT O_ORDERKEY, O_ORDERDATE FROM {T}.ORDERS WHERE O_ORDERDATE >= '2030-01-01' AND O_ORDERDATE < '2031-01-01' ORDER BY O_ORDERDATE LIMIT 20",
    f"SELECT YEAR(O_ORDERDATE) AS Y, ROUND(SUM(O_TOTALPRICE), 2) AS V FROM {T}.ORDERS GROUP BY YEAR(O_ORDERDATE)",
    f"SELECT CASE WHEN QUALITY >= 7 THEN 'good' ELSE 'other' END AS BAND, COUNT(*) FROM {W} GROUP BY 1",
    f"SELECT DATE_TRUNC('month', O_ORDERDATE) AS M, COUNT(*) FROM {T}.ORDERS GROUP BY 1",
    f"SELECT CORR(ALCOHOL, QUALITY) FROM {W}",
    f"SELECT l.L_ORDERKEY, SUM(l.L_EXTENDEDPRICE * (1 - l.L_DISCOUNT)) AS REV FROM {T}.LINEITEM l JOIN {T}.ORDERS o ON l.L_ORDERKEY = o.O_ORDERKEY GROUP BY l.L_ORDERKEY ORDER BY REV DESC LIMIT 3",
])
def test_realistic_queries_pass(sql):
    ok(sql)


@pytest.mark.parametrize("sql", [
    f"DROP TABLE {T}.ORDERS",
    f"DELETE FROM {T}.ORDERS",
    f"UPDATE {T}.ORDERS SET O_TOTALPRICE = 0",
    f"INSERT INTO {T}.ORDERS SELECT * FROM {T}.ORDERS",
    f"SELECT 1; DROP TABLE {T}.ORDERS",
    f"CREATE TABLE x AS SELECT * FROM {T}.ORDERS",
    "SELECT CURRENT_ROLE()",
])
def test_writes_and_tableless_rejected(sql):
    with pytest.raises(ValidationError):
        ok(sql)


def test_unknown_table_rejected_outright():
    with pytest.raises(ValidationError) as e:
        ok("SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
    assert not e.value.retryable


def test_unqualified_table_is_retryable():
    with pytest.raises(ValidationError) as e:
        ok("SELECT * FROM ORDERS")
    assert e.value.retryable


@pytest.mark.parametrize("sql", [
    f"SELECT SYSTEM$WAIT(10) FROM {T}.ORDERS",
    f"SELECT GET_DDL('TABLE', 'ORDERS') FROM {T}.ORDERS",
    f"SELECT CURRENT_ROLE() FROM {T}.ORDERS",
    f"SELECT UUID_STRING() FROM {T}.ORDERS",
])
def test_unapproved_functions_rejected(sql):
    with pytest.raises(ValidationError) as e:
        ok(sql)
    assert "not allowed" in str(e.value)


@pytest.mark.parametrize("sql", [
    # wrong key pair: customer key compared with order key
    f"SELECT COUNT(*) FROM {T}.CUSTOMER C JOIN {T}.ORDERS O ON C.C_CUSTKEY = O.O_ORDERKEY",
    # join without ON, and ON that is not a key comparison
    f"SELECT COUNT(*) FROM {T}.CUSTOMER C JOIN {T}.ORDERS O",
    f"SELECT COUNT(*) FROM {T}.CUSTOMER C JOIN {T}.ORDERS O ON 1 = 1",
    # comma join (implicit cross join)
    f"SELECT COUNT(*) FROM {T}.CUSTOMER C, {T}.ORDERS O",
    # joining two datasets that declare no relationship
    f"SELECT COUNT(*) FROM {T}.ORDERS O JOIN {W} W ON O.O_ORDERKEY = W.QUALITY",
])
def test_unapproved_joins_rejected(sql):
    with pytest.raises(ValidationError):
        ok(sql)


def test_join_columns_must_be_qualified():
    with pytest.raises(ValidationError) as e:
        ok(f"SELECT COUNT(*) FROM {T}.CUSTOMER C JOIN {T}.ORDERS O ON C_CUSTKEY = O_CUSTKEY")
    assert e.value.retryable
