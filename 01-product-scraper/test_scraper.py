"""Offline tests: parse a saved listing page, no network needed."""
from pathlib import Path

from scraper import Product, export_csv, export_excel, parse_listing, parse_price

FIXTURE = Path(__file__).parent / "fixtures" / "listing.html"
PAGE_URL = "https://books.toscrape.com/catalogue/page-1.html"


def test_parse_price():
    assert parse_price("£51.77") == (51.77, "£")
    assert parse_price("$1,299.00") == (1299.0, "$")


def test_parse_listing():
    products, next_url = parse_listing(FIXTURE.read_text(encoding="utf-8"), PAGE_URL)
    assert len(products) == 3
    first = products[0]
    assert first.name == "A Light in the Attic"
    assert first.price == 51.77 and first.currency == "£"
    assert first.rating == 3 and first.in_stock is True
    assert first.url == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert products[2].in_stock is False
    assert next_url == "https://books.toscrape.com/catalogue/page-2.html"


def test_exports(tmp_path):
    items = [Product("X", 10.0, "$", True, 4, "http://x"), Product("Y", 20.0, "$", False, 2, "http://y")]
    export_csv(items, tmp_path / "out.csv")
    export_excel(items, tmp_path / "out.xlsx")
    assert (tmp_path / "out.csv").read_text().count("\n") == 3
    assert (tmp_path / "out.xlsx").stat().st_size > 0
