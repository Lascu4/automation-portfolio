"""
Inventory sync: back-office system -> online store.

Reads stock levels from the source of truth (an ERP export, POS database or
spreadsheet), compares them with the online store by SKU, and pushes only the
changes. Supports dry-run, a safety buffer, and writes an audit log (CSV).

Based on a production sync I built and run daily for a supermarket
(Tango Gestión ERP -> Tiendanube store).

Usage:
    python stock_sync.py --source sample-data/erp_stock.csv --store mock --dry-run
    python stock_sync.py --source sample-data/erp_stock.csv --store mock
    python stock_sync.py --source erp.csv --store tiendanube      # needs env vars, see README
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger("stock_sync")


@dataclass
class StoreItem:
    sku: str
    stock: int
    product_id: str
    variant_id: str


@dataclass
class Change:
    sku: str
    old: int
    new: int
    product_id: str
    variant_id: str


# ---------------------------------------------------------------- source

def read_source_csv(path: str | Path, sku_col: str = "sku", stock_col: str = "stock") -> dict[str, int]:
    """Read SKU -> stock from a CSV export. Negative stock is clamped to 0, duplicate SKUs are summed."""
    stock: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            sku = (row.get(sku_col) or "").strip()
            if not sku:
                continue
            try:
                qty = int(float(row.get(stock_col) or 0))
            except ValueError:
                log.warning("Invalid stock %r for SKU %s, skipping", row.get(stock_col), sku)
                continue
            stock[sku] = stock.get(sku, 0) + max(qty, 0)
    return stock


# ---------------------------------------------------------------- stores

class Store(Protocol):
    def list_items(self) -> dict[str, StoreItem]: ...
    def update_stock(self, item: StoreItem, new_stock: int) -> None: ...


class MockStore:
    """A JSON file that behaves like a store API. Used for the demo and tests."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def list_items(self) -> dict[str, StoreItem]:
        return {
            v["sku"]: StoreItem(v["sku"], int(v["stock"]), str(p["id"]), str(v["id"]))
            for p in self._load()
            for v in p["variants"]
            if v.get("sku")
        }

    def update_stock(self, item: StoreItem, new_stock: int) -> None:
        data = self._load()
        for p in data:
            for v in p["variants"]:
                if str(v["id"]) == item.variant_id:
                    v["stock"] = new_stock
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class TiendanubeStore:
    """Tiendanube / Nuvemshop REST API adapter (products + variants)."""

    def __init__(self, store_id: str, token: str, user_agent: str):
        import requests  # imported here so the demo runs without it

        self.base = f"https://api.tiendanube.com/v1/{store_id}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authentication": f"bearer {token}",
            "User-Agent": user_agent,
            "Content-Type": "application/json",
        })

    def list_items(self) -> dict[str, StoreItem]:
        items: dict[str, StoreItem] = {}
        page = 1
        while True:
            resp = self.session.get(f"{self.base}/products", params={"page": page, "per_page": 200}, timeout=30)
            if resp.status_code == 404:  # past the last page
                break
            resp.raise_for_status()
            products = resp.json()
            if not products:
                break
            for p in products:
                for v in p.get("variants", []):
                    if v.get("sku") and v.get("stock") is not None:  # None = infinite stock
                        items[v["sku"]] = StoreItem(v["sku"], int(v["stock"]), str(p["id"]), str(v["id"]))
            page += 1
        return items

    def update_stock(self, item: StoreItem, new_stock: int) -> None:
        url = f"{self.base}/products/{item.product_id}/variants/{item.variant_id}"
        self.session.put(url, json={"stock": new_stock}, timeout=30).raise_for_status()


# ---------------------------------------------------------------- core

def plan_changes(source: dict[str, int], store: dict[str, StoreItem], buffer: int = 0) -> tuple[list[Change], list[str]]:
    """Compare source vs store. Returns the changes to apply and SKUs that exist only in the store."""
    changes, missing = [], []
    for sku, item in sorted(store.items()):
        if sku not in source:
            missing.append(sku)
            continue
        target = max(source[sku] - buffer, 0)
        if target != item.stock:
            changes.append(Change(sku, item.stock, target, item.product_id, item.variant_id))
    return changes, missing


def apply_changes(store: Store, changes: list[Change], dry_run: bool, audit_path: str | Path) -> int:
    new_file = not Path(audit_path).exists()
    ok = 0
    with open(audit_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["timestamp", "sku", "old_stock", "new_stock", "status"])
        for c in changes:
            status = "dry-run"
            if not dry_run:
                try:
                    store.update_stock(StoreItem(c.sku, c.old, c.product_id, c.variant_id), c.new)
                    status, ok = "updated", ok + 1
                except Exception as exc:  # keep going, log the failure
                    status = f"error: {exc}"
                    log.error("Failed to update %s: %s", c.sku, exc)
            writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), c.sku, c.old, c.new, status])
            log.info("%-10s %4d -> %-4d %s", c.sku, c.old, c.new, status)
    return ok


def build_store(kind: str, mock_path: str) -> Store:
    if kind == "mock":
        return MockStore(mock_path)
    if kind == "tiendanube":
        return TiendanubeStore(os.environ["TN_STORE_ID"], os.environ["TN_TOKEN"],
                               os.environ.get("TN_USER_AGENT", "StockSync (contact@example.com)"))
    raise ValueError(f"Unknown store: {kind}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="CSV with sku,stock columns")
    ap.add_argument("--store", default="mock", choices=["mock", "tiendanube"])
    ap.add_argument("--mock-file", default="sample-data/store.json")
    ap.add_argument("--buffer", type=int, default=0, help="Units held back from the online store")
    ap.add_argument("--dry-run", action="store_true", help="Show changes without applying them")
    ap.add_argument("--audit", default="sync_audit.csv")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source = read_source_csv(args.source)
    store = build_store(args.store, args.mock_file)
    changes, missing = plan_changes(source, store.list_items(), args.buffer)

    log.info("Source SKUs: %d | changes: %d | only in store: %d", len(source), len(changes), len(missing))
    if missing:
        log.warning("SKUs in the store but not in the source: %s", ", ".join(missing))
    updated = apply_changes(store, changes, args.dry_run, args.audit)
    log.info("Done. %s", "Dry run, nothing changed." if args.dry_run else f"{updated}/{len(changes)} updated.")


if __name__ == "__main__":
    main()
