# Automation Portfolio — Tadeo García Areán

Python & Google Sheets automations for small businesses: scrapers, reports, and inventory integrations.
Everything here is tested and documented. These are demo versions of the kind of work I deliver to clients.

| Project | What it solves | Stack |
|---|---|---|
| [01 · Product scraper](01-product-scraper/) | Turns any paginated product catalog into a clean CSV + formatted Excel report | Python, requests, BeautifulSoup, openpyxl |
| [02 · Sheets sales & stock automation](02-sheets-automation/) | Custom menu, data cleaning, daily sales report with chart, low-stock email alerts | Google Apps Script |
| [03 · Inventory sync](03-stock-sync/) | Keeps online store stock in sync with the back-office system: dry-run, safety buffer, audit log | Python, REST APIs (Tiendanube adapter included) |

## Background
I run the tech side of a family supermarket. I built and maintain its inventory system
(Python/Flask + PostgreSQL + React) and a daily stock sync between the ERP (Tango Gestión) and the online store.
Project 03 is a cleaned-up, generic version of that production sync.

## Run the Python projects
```bash
cd 01-product-scraper     # or 03-stock-sync
pip install -r requirements.txt
python -m pytest -q
```

---

## 01 · Product scraper
```bash
python scraper.py --pages 3 --out products     # products.csv + products.xlsx
```
- Pagination, retries with backoff, polite delay between requests
- Price/currency parsing, ratings, stock status
- Excel output with styled header, filters, frozen row and a summary sheet
- Offline tests with a saved HTML fixture

## 02 · Google Sheets automation
1. Create a sheet with tabs `Sales` and `Inventory` (import the CSVs in `sample-data/`).
2. Extensions → Apps Script → paste `Code.gs` → save → reload the sheet.
3. Use the new **Automation** menu. Run *Install daily trigger* once for the 8 AM job.

## 03 · Inventory sync
```bash
python stock_sync.py --source sample-data/erp_stock.csv --store mock --dry-run
python stock_sync.py --source sample-data/erp_stock.csv --store mock --buffer 2
```
For a real Tiendanube store set `TN_STORE_ID`, `TN_TOKEN` and `TN_USER_AGENT`, then use `--store tiendanube`.
- Only pushes changed SKUs; clamps negative stock; sums duplicate SKUs; skips invalid rows
- Reports SKUs that exist only in the store
- Every run is appended to `sync_audit.csv`
- New platforms (Shopify, WooCommerce, Mercado Libre) plug in by implementing two methods: `list_items` and `update_stock`

## Contact
Available for fixed-price automation work. Async communication (chat/email), fast turnaround.
