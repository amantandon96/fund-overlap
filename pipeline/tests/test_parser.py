"""Sheet parser tests on small synthetic workbooks (no downloaded files needed)."""

import io

import openpyxl
import pytest

from fund_overlap.adapters import find_as_of, slugify, split_title
from fund_overlap.parser import clean_name, parse_rows

HEADER = [None, "ISIN", "Name of the Instrument", "Industry / Rating", "Quantity",
          "Market/Fair Value\n( Rs. in Lacs)", "% to NAV", "YIELD"]


def rows_via_workbook(rows):
    """Round-trip rows through a real xlsx so cell types match production reads."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    ws = openpyxl.load_workbook(buf, read_only=True, data_only=True).active
    return list(ws.iter_rows(values_only=True))


def sheet(equity, grand_total, extra_after=()):
    rows = [
        ["X01", "Sample Flexi Cap Fund (An open ended equity scheme)"],
        [None, "Monthly Portfolio Statement as on October 31, 2026"],
        [],
        HEADER,
        [None, None, "Equity & Equity related"],
        [None, None, "(a) Listed / awaiting listing on Stock Exchanges"],
        *equity,
        [None, None, "Subtotal", None, None, 1000.0, sum(r[6] for r in equity if isinstance(r[6], (int, float)))],
        [None, None, "(b) UNLISTED", None, None, "NIL", "NIL"],
        [None, None, "Total", None, None, 1000.0, 0],
        *extra_after,
        [None, None, "GRAND TOTAL", None, None, 5000.0, grand_total],
    ]
    return rows_via_workbook(rows)


DEBT = (
    [None, None, "Debt Instruments"],
    [None, "INE001A07AB1", "8% Some Corp NCD", "CRISIL AAA", 10, 100.0, 0.05],
    [None, None, "Total", None, None, 100.0, 0.05],
)


def test_fraction_weights_are_scaled_to_percent():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 0.06],
         [None, "INE090A01021", "ICICI Bank Limited", "Banks", 100, 400.0, 0.04]],
        grand_total=1,
    ))
    assert parsed.header_found and parsed.equity_section_found
    assert parsed.unit == "fraction"
    assert [(h.isin, round(h.weight, 4)) for h in parsed.holdings] == [
        ("INE040A01034", 6.0), ("INE090A01021", 4.0)]
    assert parsed.holdings[0].industry == "Banks"


def test_percent_weights_are_kept():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 9.28],
         [None, "INE090A01021", "ICICI Bank Limited", "Banks", 100, 400.0, 5.79]],
        grand_total=100,
    ))
    assert parsed.unit == "percent"
    assert [round(h.weight, 2) for h in parsed.holdings] == [9.28, 5.79]
    assert round(parsed.equity_pct, 2) == 15.07


def test_small_percent_weights_are_not_mistaken_for_fractions():
    # A hybrid fund holding 0.4% + 0.3% equity: only the grand total tells the unit.
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 1, 4.0, 0.4],
         [None, "INE090A01021", "ICICI Bank Limited", "Banks", 1, 3.0, 0.3]],
        grand_total=100,
    ))
    assert parsed.unit == "percent"
    assert [round(h.weight, 2) for h in parsed.holdings] == [0.4, 0.3]


def test_default_unit_used_only_without_grand_total():
    rows = sheet([[None, "INE040A01034", "HDFC Bank Limited", "Banks", 1, 4.0, 0.4]], grand_total=100)[:-1]
    assert parse_rows(rows, default_unit="percent").holdings[0].weight == pytest.approx(0.4)
    assert parse_rows(rows, default_unit="fraction").holdings[0].weight == pytest.approx(40.0)
    assert parse_rows(rows).unit == "fraction"  # heuristic of last resort


def test_duplicate_isin_weights_are_summed():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 3.0],
         [None, "INE090A01021", "ICICI Bank Limited", "Banks", 100, 400.0, 4.0],
         [None, "INE040A01034", "HDFC Bank Limited", "Banks", 50, 300.0, 1.5]],
        grand_total=100,
    ))
    assert [(h.isin, round(h.weight, 4)) for h in parsed.holdings] == [
        ("INE040A01034", 4.5), ("INE090A01021", 4.0)]


def test_footnote_marks_are_stripped_from_names():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Ltd.£", "Banks", 100, 600.0, 5.0],
         [None, "INE090A01021", "  ICICI Bank Ltd. ** ", "Banks", 100, 400.0, 4.0]],
        grand_total=100,
    ))
    assert [h.name for h in parsed.holdings] == ["HDFC Bank Ltd.", "ICICI Bank Ltd."]
    assert clean_name("Some Co Ltd #") == "Some Co Ltd"
    assert clean_name("L&T Finance Ltd") == "L&T Finance Ltd"


def test_equity_section_ends_at_total_so_debt_rows_are_excluded():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 0.06]],
        grand_total=1,
        extra_after=DEBT,
    ))
    assert [h.isin for h in parsed.holdings] == ["INE040A01034"]
    assert parsed.grand_total == 1


def test_equity_section_ends_at_next_heading_even_without_total_row():
    rows = rows_via_workbook([
        HEADER,
        [None, None, "EQUITY & EQUITY RELATED"],
        [None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 60],
        [None, None, "DEBT INSTRUMENTS"],
        [None, "INE001A07AB1", "8% Some Corp NCD", "CRISIL AAA", 10, 100.0, 40],
        [None, None, "Grand Total", None, None, 700.0, 100],
    ])
    parsed = parse_rows(rows)
    assert [h.isin for h in parsed.holdings] == ["INE040A01034"]


def test_rows_without_valid_isin_or_numeric_weight_are_skipped():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 5.0],
         [None, "INE090A01021", "Tiny Position Ltd", "Banks", 1, 0.01, "$"],
         [None, None, "Some Stock Future", None, -10, -5.0, -0.5],
         [None, "NOTANISIN", "Broken Row", "Banks", 1, 1.0, 1.0]],
        grand_total=100,
    ))
    assert [h.isin for h in parsed.holdings] == ["INE040A01034"]
    assert parsed.tiny_rows == 1
    assert parsed.unparsed_equity_rows == 1


def test_sheet_without_equity_section_yields_nothing():
    rows = rows_via_workbook([
        ["Sample Liquid Fund"],
        HEADER,
        *DEBT,
        [None, None, "GRAND TOTAL", None, None, 100.0, 1],
    ])
    parsed = parse_rows(rows)
    assert parsed.header_found and not parsed.equity_section_found and parsed.holdings == []


def test_sheet_without_isin_header_is_reported():
    parsed = parse_rows(rows_via_workbook([["Sr No.", "Short Name", "Scheme Name"], [1, "GF", "Some Fund"]]))
    assert not parsed.header_found


def test_column_order_is_taken_from_the_header():
    # Motilal/Axis/Navi put the name before the ISIN and call the weight "% to Net Assets".
    rows = rows_via_workbook([
        ["Sr. No.", "Name of the Instrument", "ISIN", "Industry*", "Quantity",
         "Market/Fair Value (Rs. in Lakhs)", "% to Net\n Assets"],
        ["(A)", "Equity & Equity related"],
        [1, "HDFC Bank Limited", "INE040A01034", "Banks", 10, 739.5, 9.95],
        [None, "Total", None, None, None, 739.5, 9.95],
        [None, "GRAND TOTAL", None, None, None, 7000.0, 100],
    ])
    parsed = parse_rows(rows)
    assert [(h.isin, h.name, h.industry, h.weight) for h in parsed.holdings] == [
        ("INE040A01034", "HDFC Bank Limited", "Banks", 9.95)]


def test_split_title_and_slug():
    assert split_title("HDFC Flexi Cap Fund (An open ended dynamic equity scheme)") == (
        "HDFC Flexi Cap Fund", "An open ended dynamic equity scheme")
    assert split_title("Motilal Oswal Midcap Fund (Formerly known as Motilal Oswal Midcap 30 Fund)") == (
        "Motilal Oswal Midcap Fund", None)
    assert split_title("Axis Capital Builder Fund - Series 4 (1582 days)") == (
        "Axis Capital Builder Fund - Series 4 (1582 days)", None)
    assert split_title("NIPPON INDIA BANKING & FINANCIAL SERVICES FUND (An Open Ended Equity Scheme)")[0] == (
        "Nippon India Banking & Financial Services Fund")
    assert slugify("Navi Large & Midcap Fund") == "navi-large-and-midcap-fund"


def test_find_as_of_formats():
    from datetime import date

    assert find_as_of([["Monthly Portfolio Statement as on October 31, 2026"]]) == date(2026, 10, 31)
    assert find_as_of([["Portfolio as on 31-Oct-2026"]]) == date(2026, 10, 31)
    assert find_as_of([["MONTHLY PORTFOLIO STATEMENT AS ON 31st October 2026"]]) == date(2026, 10, 31)
    assert find_as_of([["Sample Fund"]]) is None


def test_motilal_title_with_and_without_brackets():
    from fund_overlap.adapters import ADAPTERS

    title = ADAPTERS["motilal"].title
    top = [["Back to Index"], ["Motilal Oswal Asset Management Company Limited"],
           ["MONTHLY PORTFOLIO STATEMENT AS ON OCTOBER 31, 2026"], [None]]
    assert split_title(title(top + [["Motilal Oswal Midcap Fund"], ["(An open ended equity scheme)"]])) == (
        "Motilal Oswal Midcap Fund", "An open ended equity scheme")
    assert split_title(title(top + [["Motilal Oswal Nifty 500 Index Fund"], ["An open ended scheme tracking Nifty 500"]])) == (
        "Motilal Oswal Nifty 500 Index Fund", "An open ended scheme tracking Nifty 500")


FOREIGN = (
    [None, None, "Equity & Equity related Foreign Investments"],
    [None, "US02079K3059", "Alphabet Inc A", "Software ##", 10, 300.0, 0.03],
    [None, None, "Total", None, None, 300.0, 0.03],
)


def test_second_equity_section_is_ignored_by_default():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 0.06]],
        grand_total=1, extra_after=FOREIGN,
    ))
    assert [h.isin for h in parsed.holdings] == ["INE040A01034"]


def test_second_equity_section_is_kept_when_multi_equity():
    parsed = parse_rows(sheet(
        [[None, "INE040A01034", "HDFC Bank Limited", "Banks", 100, 600.0, 0.06]],
        grand_total=1, extra_after=(*FOREIGN, *DEBT),
    ), multi_equity=True)
    assert [h.isin for h in parsed.holdings] == ["INE040A01034", "US02079K3059"]  # largest weight first
    assert round(parsed.equity_pct, 2) == 9.0  # debt after the foreign section stays out
