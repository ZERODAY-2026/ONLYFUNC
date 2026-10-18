"""Visualisation: data ki shakal se chart ka type tay hota hai, aur har chart sirf Snowflake se aayi rows se banta hai (offline)."""
from datetime import date
from decimal import Decimal

import pytest

from datamind import viz


def plan_for(columns, rows, question=""):
    frame = viz.to_frame(columns, rows)
    return frame, viz.suggest(frame, question)


def all_charts_are_valid(frame, plan):
    """Har chart type aur har X/Y combination ka Vega-Lite spec valid hona chahiye."""
    for chart_type in plan.types:
        if chart_type == "metric":
            continue
        for x in [None] + plan.x_options:
            for y in [None] + plan.y_options:
                built = viz.make_chart(frame, plan, chart_type, y=y, x=x)
                if built is not None:
                    assert built.chart.to_dict()["$schema"].startswith("https://vega.github.io/schema/vega-lite")


def test_label_plus_number_is_a_bar_chart():
    frame, plan = plan_for(["ENTITY", "GDP"], [("Luxembourg", 129865.63), ("Singapore", 116684.21), ("Qatar", 103061.9)], "Which countries are richest?")
    assert plan.default == "bar" and plan.x == "ENTITY" and plan.y_options == ["GDP"]
    all_charts_are_valid(frame, plan)


def test_year_plus_number_is_a_line_and_the_question_can_confirm_it():
    rows = [(2000 + i, 62 + i * 0.4) for i in range(24)]
    frame, plan = plan_for(["YEAR", "LIFE_EXPECTANCY"], rows, "How has life expectancy changed since 2000?")
    assert plan.kinds["YEAR"] == "temporal" and plan.default == "line" and "line" in plan.reason.lower()
    all_charts_are_valid(frame, plan)


def test_real_dates_are_a_time_axis():
    rows = [(date(2020, m, 1), m * 2) for m in range(1, 7)]
    frame, plan = plan_for(["ORDER_MONTH", "N"], rows, "orders per month")
    assert plan.kinds["ORDER_MONTH"] == "temporal" and plan.default == "line"
    assert viz.make_chart(frame, plan, "line").chart.to_dict()["encoding"]["x"]["type"] == "temporal"


def test_single_row_is_shown_as_numbers_not_a_chart():
    frame, plan = plan_for(["N"], [(150000,)], "How many customers?")
    assert plan.types == ["metric"] and plan.default == "metric" and plan.y_options == ["N"]
    assert viz.make_chart(frame, plan, "metric") is None


def test_share_wording_picks_a_donut_only_when_it_is_readable():
    rows = [("ASIA", 5), ("EUROPE", 3), ("AFRICA", 2)]
    _, plan = plan_for(["REGION", "REVENUE"], rows, "What share of revenue comes from each region?")
    assert "donut" in plan.types and plan.default == "donut"
    many = [(f"R{i}", i + 1) for i in range(12)]
    _, plan = plan_for(["REGION", "REVENUE"], many, "What share of revenue comes from each region?")
    assert "donut" not in plan.types and plan.default == "bar"           # 12 hisse padhne layak nahi
    _, plan = plan_for(["REGION", "PROFIT"], [("A", 5), ("B", -3)], "share of profit")
    assert "donut" not in plan.types                                      # negative values donut me nahi


def test_two_numbers_make_a_scatter_and_distribution_wording_a_histogram():
    rows = [(9 + i * 0.1, 3 + (i % 6) * 1.5) for i in range(40)]
    frame, plan = plan_for(["ALCOHOL", "SUGAR"], rows, "relationship between alcohol and sugar")
    assert plan.default == "scatter" and "histogram" in plan.types
    all_charts_are_valid(frame, plan)
    _, plan = plan_for(["AGE"], [(20 + i,) for i in range(30)], "distribution of ages")
    assert plan.types == ["histogram"]


def test_a_score_column_is_the_axis_and_the_category_is_the_series():
    rows = [(q, c, 9 + q * 0.3) for q in (3, 4, 5, 6) for c in ("red", "white")]
    frame, plan = plan_for(["QUALITY", "COLOR", "AVG(ALCOHOL)"], rows, "average alcohol by quality and colour")
    assert plan.x == "QUALITY" and plan.series == "COLOR" and plan.y_options == ["AVG(ALCOHOL)"]
    all_charts_are_valid(frame, plan)                                      # AVG(ALCOHOL) jaisa naam encoding nahi bigadta


def test_text_only_results_get_no_chart():
    _, plan = plan_for(["NAME", "COMMENT"], [("a", "x"), ("b", "y")])
    assert plan is None
    assert viz.suggest(viz.to_frame(["N"], []), "q") is None


def test_id_and_key_columns_are_labels_not_measures():
    frame, plan = plan_for(["O_CUSTKEY", "TOTAL"], [(1, 10.5), (2, 20.5), (3, 5.0)], "top customers")
    assert plan.kinds["O_CUSTKEY"] == "category" and plan.y_options == ["TOTAL"]


def test_results_reloaded_from_a_saved_chat_still_chart():
    """Saved chat me Decimal aur date text ban jaate hain; chart phir bhi banna chahiye."""
    live = [(Decimal("2019"), Decimal("83000000.5")), (Decimal("2020"), Decimal("83628711")), (Decimal("2021"), Decimal("83900000"))]
    saved = [("2019", "83000000.5"), ("2020", "83628711"), ("2021", "83900000")]
    for rows in (live, saved):
        frame, plan = plan_for(["YEAR", "POPULATION"], rows, "population over time")
        assert plan.default == "line" and frame["POPULATION"].dtype.kind == "f"
        assert viz.make_chart(frame, plan, "line").chart.to_dict()


def test_many_bars_are_capped_and_the_cap_is_stated():
    rows = [(f"job{i}", i * 0.7) for i in range(viz.MAX_BARS + 10)]
    frame, plan = plan_for(["JOB", "RATE"], rows, "rate by job")
    built = viz.make_chart(frame, plan, "bar")
    assert f"top {viz.MAX_BARS} of {viz.MAX_BARS + 10}" in built.note
    assert len(built.chart.to_dict()["datasets"][next(iter(built.chart.to_dict()["datasets"]))]) == viz.MAX_BARS


def test_charts_only_contain_the_returned_values():
    rows = [("A", 1.5), ("B", 2.5), ("C", 3.5)]
    frame, plan = plan_for(["LABEL", "VALUE"], rows, "values")
    spec = viz.make_chart(frame, plan, "bar").chart.to_dict()
    data = next(iter(spec["datasets"].values()))
    assert sorted(d["c1"] for d in data) == [1.5, 2.5, 3.5]               # koi nayi/andaza wali value nahi


def test_duplicate_column_names_do_not_crash():
    frame, plan = plan_for(["N", "N"], [(1, 2), (3, 4), (5, 6)], "two counts")
    assert list(frame.columns) == ["N", "N_2"]


def test_unknown_axis_or_chart_type_falls_back_safely():
    frame, plan = plan_for(["ENTITY", "GDP"], [("A", 1.0), ("B", 2.0), ("C", 3.0)])
    assert viz.make_chart(frame, plan, "line") is None                    # is data ke liye line possible nahi
    assert viz.make_chart(frame, plan, "bar", y="NOPE", x="ALSO_NOPE") is not None   # galat naam par default use hota hai
