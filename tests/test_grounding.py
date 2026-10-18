from datamind.grounding import evidence_fallback, numbers_grounded

Q = "How many orders are there?"
SQL = "SELECT COUNT(*) AS ORDER_COUNT FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS"


def grounded(text, rows, question=Q, sql=SQL, assumptions=()):
    return numbers_grounded(text, question, sql, list(assumptions), rows)


def test_exact_number_is_grounded():
    assert grounded("There are 42 orders.", [(42,)])


def test_thousands_separators_are_understood():
    assert grounded("There are 1,500,000 orders.", [(1500000,)])


def test_invented_number_is_not_grounded():
    assert not grounded("There were 999 fabricated orders.", [(42,)])


def test_rounding_of_a_row_value_is_grounded():
    assert grounded("The average is 10.59.", [(10.58755289138787,)])
    assert not grounded("The average is 10.60.", [(10.58755289138787,)])


def test_list_numbering_and_row_count_are_allowed():
    rows = [("A", 5.5), ("B", 4.5), ("C", 3.5)]
    assert grounded("3 rows: 1) A 5.5, 2) B 4.5, 3) C 3.5", rows)


def test_numbers_from_question_sql_and_assumptions_are_allowed():
    assert grounded("Top 5 customers in 1995.", [("A", 9.0)], question="top 5 customers", assumptions=["year 1995"])


def test_ids_with_digits_inside_strings_are_grounded():
    assert grounded("Customer#000143500 spent 7,012,696.48.", [("Customer#000143500", 7012696.48)])


def test_fallback_uses_first_row_and_count():
    text = evidence_fallback(["N"], [(42,)])
    assert "N: 42" in text
    many = evidence_fallback(["A", "B"], [(1, 2), (3, 4)])
    assert "2 result rows" in many and "A: 1, B: 2" in many
