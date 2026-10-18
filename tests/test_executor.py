"""Fake Snowflake connection ke saath executor tests (network nahi, credentials nahi)."""
import pytest
import snowflake.connector.errors as sf_errors

from datamind.executor import SnowflakeExecutor, _unique


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.sfqid, self.description = conn, "qid-1", [("A",), ("B",)]

    def execute(self, sql):
        self.conn.executed.append(sql)
        if self.conn.failures:
            raise self.conn.failures.pop(0)

    def fetchmany(self, n):
        return self.conn.rows[:n]

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows=((1, "x"),), failures=()):
        self.rows, self.failures, self.executed, self.closed = list(rows), list(failures), [], False

    def cursor(self):
        return FakeCursor(self)

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class Factory:
    """connect_fn jo fake connections deta hai aur logins ginta hai."""
    def __init__(self, *conns):
        self.conns, self.logins = list(conns), 0

    def __call__(self, role_var):
        self.logins += 1
        return self.conns.pop(0)


def executor(factory, **kw):
    return SnowflakeExecutor(connect_fn=factory, **kw)


def test_result_has_dict_rows_columns_query_id_and_flag():
    ex = executor(Factory(FakeConn(rows=[(1, "x"), (2, "y")])))
    r = ex("SELECT A, B FROM T")
    assert r == {"rows": [{"A": 1, "B": "x"}, {"A": 2, "B": "y"}], "columns": ["A", "B"], "query_id": "qid-1", "truncated": False}


def test_result_cap_truncates_and_flags():
    ex = executor(Factory(FakeConn(rows=[(i, "x") for i in range(5)])), max_rows=2)
    r = ex("SELECT A, B FROM T")
    assert len(r["rows"]) == 2 and r["truncated"] is True


@pytest.mark.parametrize("sql", ["DROP TABLE T", "delete from t", "UPDATE t SET a = 1", "INSERT INTO t VALUES (1)", "", "  ", None])
def test_only_select_or_with_run_and_nothing_connects_otherwise(sql):
    f = Factory(FakeConn())
    with pytest.raises(ValueError):
        executor(f)(sql)
    assert f.logins == 0


@pytest.mark.parametrize("sql", ["select 1", "  SELECT A FROM T", "WITH c AS (SELECT 1) SELECT * FROM c"])
def test_select_and_with_are_allowed(sql):
    assert executor(Factory(FakeConn()))(sql)["query_id"] == "qid-1"


def test_sql_errors_propagate_without_retry_or_reconnect():
    f = Factory(FakeConn(failures=[sf_errors.ProgrammingError(msg="bad column", errno=904)]), FakeConn())
    with pytest.raises(sf_errors.ProgrammingError):
        executor(f)("SELECT nope FROM T")
    assert f.logins == 1


def test_expired_session_reconnects_once_and_succeeds():
    old = FakeConn(failures=[sf_errors.DatabaseError(msg="token expired", errno=390114)])
    f = Factory(old, FakeConn(rows=[(7, "z")]))
    r = executor(f)("SELECT A, B FROM T")
    assert r["rows"] == [{"A": 7, "B": "z"}] and f.logins == 2 and old.closed


def test_network_failure_reconnects_once_and_a_second_failure_is_raised():
    down = [sf_errors.OperationalError(msg="network", errno=250003)]
    f = Factory(FakeConn(failures=list(down)), FakeConn(failures=list(down)))
    with pytest.raises(sf_errors.OperationalError):
        executor(f)("SELECT A, B FROM T")
    assert f.logins == 2  # bilkul ek retry, koi loop nahi


def test_unrelated_database_error_is_not_retried():
    f = Factory(FakeConn(failures=[sf_errors.DatabaseError(msg="other", errno=12345)]), FakeConn())
    with pytest.raises(sf_errors.DatabaseError):
        executor(f)("SELECT A, B FROM T")
    assert f.logins == 1


def test_closed_connection_is_reopened_before_use():
    first = FakeConn()
    f = Factory(first, FakeConn())
    ex = executor(f)
    ex("SELECT A, B FROM T")
    first.closed = True
    ex("SELECT A, B FROM T")
    assert f.logins == 2


def test_context_manager_closes_the_connection():
    conn = FakeConn()
    with executor(Factory(conn)) as ex:
        ex("SELECT A, B FROM T")
    assert conn.closed


def test_duplicate_column_names_get_unique_keys():
    assert _unique(["ID", "ID", "N", "ID"]) == ["ID", "ID_2", "N", "ID_3"]
