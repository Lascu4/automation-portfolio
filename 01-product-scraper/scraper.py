"""
Product catalog scraper -> CSV / Excel.

Crawls a paginated product listing, extracts name, price, stock and rating,
and exports a clean CSV and a formatted Excel report.

Demo target: https://books.toscrape.com (a public sandbox built for scraping practice).

Usage:
    python scraper.py --pages 3 --out products
    python scraper.py --pages 0 --out all_products      # 0 = crawl every page
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from dataclasses import dataclass, asdict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

BASE_URL = "https://books.toscrape.com/catalogue/page-1.html"
RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-demo scraper)"}

log = logging.getLogger("scraper")


@dataclass
class Product:
    name: str
    price: float
    currency: str
    in_stock: bool
    rating: int
    url: str


def fetch(session: requests.Session, url: str, retries: int = 3, backoff: float = 1.5) -> str:
    """GET a page with retries and exponential backoff."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            wait = backoff ** attempt
            log.warning("Attempt %d failed for %s (%s). Retrying in %.1fs", attempt, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def parse_price(text: str) -> tuple[float, str]:
    match = re.search(r"([^\d\s.,]*)\s*([\d.,]+)", text.strip())
    if not match:
        raise ValueError(f"Cannot parse price: {text!r}")
    currency, number = match.groups()
    return float(number.replace(",", "")), currency or "?"


def parse_listing(html: str, page_url: str) -> tuple[list[Product], str | None]:
    """Return the products on a listing page and the URL of the next page (or None)."""
    soup = BeautifulSoup(html, "html.parser")
    products: list[Product] = []
    for card in soup.select("article.product_pod"):
        link = card.select_one("h3 a")
        price, currency = parse_price(card.select_one(".price_color").get_text())
        rating_cls = next((c for c in card.select_one(".star-rating")["class"] if c in RATINGS), None)
        products.append(
            Product(
                name=link["title"].strip(),
                price=price,
                currency=currency,
                in_stock="In stock" in card.select_one(".availability").get_text(),
                rating=RATINGS.get(rating_cls, 0),
                url=urljoin(page_url, link["href"]),
            )
        )
    nxt = soup.select_one("li.next a")
    return products, (urljoin(page_url, nxt["href"]) if nxt else None)


def crawl(start_url: str, max_pages: int = 0, delay: float = 0.5) -> list[Product]:
    session = requests.Session()
    url, page, results = start_url, 0, []
    while url and (max_pages == 0 or page < max_pages):
        page += 1
        log.info("Page %d: %s", page, url)
        items, url = parse_listing(fetch(session, url), url)
        results.extend(items)
        time.sleep(delay)  # be polite to the server
    return results


def export_csv(products: list[Product], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Product.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(p) for p in products)


def export_excel(products: list[Product], path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    cols = list(Product.__dataclass_fields__)
    ws.append([c.replace("_", " ").title() for c in cols])
    for p in products:
        ws.append([getattr(p, c) for c in cols])
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for i, col in enumerate(cols, start=1):
        width = max(len(str(ws.cell(r, i).value or "")) for r in range(1, ws.max_row + 1))
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    summary = wb.create_sheet("Summary")
    n = len(products) or 1
    summary.append(["Metric", "Value"])
    summary.append(["Products scraped", len(products)])
    summary.append(["Average price", round(sum(p.price for p in products) / n, 2)])
    summary.append(["In stock (%)", round(100 * sum(p.in_stock for p in products) / n, 1)])
    summary.append(["Average rating", round(sum(p.rating for p in products) / n, 2)])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 20
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=BASE_URL, help="First listing page")
    ap.add_argument("--pages", type=int, default=3, help="Max pages to crawl (0 = all)")
    ap.add_argument("--out", default="products", help="Output file name without extension")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    products = crawl(args.url, args.pages)
    export_csv(products, f"{args.out}.csv")
    export_excel(products, f"{args.out}.xlsx")
    log.info("Done: %d products -> %s.csv / %s.xlsx", len(products), args.out, args.out)


if __name__ == "__main__":
    main()
