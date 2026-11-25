import json
import shutil
from pathlib import Path

from stock_sync import MockStore, apply_changes, plan_changes, read_source_csv

DATA = Path(__file__).parent / "sample-data"


def test_read_source_cleans_data():
    src = read_source_csv(DATA / "erp_stock.csv")
    assert src["7790004"] == 0          # negative clamped
    assert src["7790005"] == 50         # duplicates summed
    assert "7790006" not in src         # invalid stock skipped


def test_plan_and_apply(tmp_path):
    store_file = tmp_path / "store.json"
    shutil.copy(DATA / "store.json", store_file)
    store = MockStore(store_file)

    changes, missing = plan_changes(read_source_csv(DATA / "erp_stock.csv"), store.list_items())
    assert {c.sku: c.new for c in changes} == {"7790001": 24, "7790002": 0, "7790004": 0, "7790005": 50}
    assert missing == ["GIFT-01"]

    apply_changes(store, changes, dry_run=True, audit_path=tmp_path / "audit.csv")
    assert store.list_items()["7790001"].stock == 30   # dry run changes nothing

    assert apply_changes(store, changes, dry_run=False, audit_path=tmp_path / "audit.csv") == 4
    after = {v["sku"]: v["stock"] for p in json.loads(store_file.read_text()) for v in p["variants"]}
    assert after["7790001"] == 24 and after["7790005"] == 50 and after["GIFT-01"] == 99


def test_buffer():
    from stock_sync import StoreItem
    changes, _ = plan_changes({"A": 5}, {"A": StoreItem("A", 5, "1", "1")}, buffer=2)
    assert changes[0].new == 3
