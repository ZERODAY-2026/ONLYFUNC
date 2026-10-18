from datetime import date
from decimal import Decimal

from eval.compare import match, norm, row_covers


def test_norm_makes_snowflake_values_comparable():
    assert norm(Decimal("12.50")) == 12.5 and norm(7) == 7.0
    assert norm(" EUROPE ") == "europe" and norm(date(1995, 3, 1)) == "1995-03-01" and norm(None) is None


def test_scalar_matches_exact_and_rounded_values():
    assert match([(1500000,)], [(1500000,)], "scalar")[0]
    assert match([(10.58755289,)], [(10.59,)], "scalar")[0]            # ROUND(x, 2) chalega
    assert match([(42,)], [("orders", 42)], "scalar")[0]               # extra label column chalega
    ok, why = match([(42,)], [(43,)], "scalar")
    assert not ok and "expected 42" in why


def test_scalar_needs_exactly_one_row():
    assert not match([(5,)], [(5,), (6,)], "scalar")[0]
    assert not match([(0,)], [], "scalar")[0]


def test_small_count_differences_are_not_tolerated():
    assert not match([(50000,)], [(49999,)], "scalar")[0]


def test_rows_unordered_with_extra_columns():
    truth = [("EUROPE", 30197), ("ASIA", 30183)]
    answer = [("ASIA", 30183, "x"), ("EUROPE", 30197, "y")]
    assert match(truth, answer, "rows")[0]


def test_rows_wrong_count_or_value():
    assert "expected 2 rows" in match([("A", 1), ("B", 2)], [("A", 1)], "rows")[1]
    assert not match([("A", 1), ("B", 2)], [("A", 1), ("B", 3)], "rows")[0]


def test_ordered_rankings_care_about_order():
    truth = [("A", 9), ("B", 8)]
    assert match(truth, [("A", 9), ("B", 8)], "rows", ordered=True)[0]
    ok, why = match(truth, [("B", 8), ("A", 9)], "rows", ordered=True)
    assert not ok and "row 1" in why


def test_contains_allows_extra_rows_but_requires_the_truth_row():
    assert match([("white", 5.877909)], [("red", 5.6), ("white", 5.88)], "contains")[0]
    assert not match([("white", 5.877909)], [("red", 5.6)], "contains")[0]


def test_text_is_case_insensitive_and_dates_compare_as_text():
    assert row_covers(("Europe", date(1997, 1, 1)), ("EUROPE", "1997-01-01"))
