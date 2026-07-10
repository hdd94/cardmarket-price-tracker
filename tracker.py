import json
import math
import os
import random
import sys
from datetime import date, timedelta

import requests

# ---------------------------------------------------------------------------
# Configuration — map idProduct (as string) to human-readable name
# ---------------------------------------------------------------------------
TARGETS: dict[str, str] = {
    "812570": "Duskmourn Collector Booster Display",
    "794120": "Bloomburrow Collector Booster Display",
    "775932": "Outlaws of Thunder Junction Collector Booster Display",
}

PRICE_HISTORY_FILE = "price_history.json"

PRICE_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_2.json"
)

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_price_guide() -> list[dict]:
    """Download and return the full Price Guide JSON array from Cardmarket."""
    response = requests.get(PRICE_GUIDE_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_price_guide_mock() -> list[dict]:
    """
    Return a realistic 90-day simulated Price Guide payload for local testing.
    Generates smooth price curves with noise so charts look meaningful.
    Only used when --mock flag is passed; writes all 90 days into history.
    """
    base_prices = {
        812570: 8.50,
        794120: 130.00,
        775932: 102.00,
    }

    today = date.today()
    entries_by_date: dict[str, list[dict]] = {}

    for days_ago in range(89, -1, -1):
        day = today - timedelta(days=days_ago)
        day_str = day.isoformat()
        daily_entries = []
        for pid, base in base_prices.items():
            # Slow sinusoidal drift + bounded random walk
            t = days_ago / 30.0
            drift = base * 0.12 * math.sin(t * math.pi)
            noise = base * random.uniform(-0.03, 0.03)
            trend = round(max(base * 0.6, base + drift + noise), 2)
            daily_entries.append({"idProduct": pid, "idCategory": 2, "trend": trend})
        entries_by_date[day_str] = daily_entries

    # Expose as a flat list tagged with date so update_history can iterate
    result = []
    for day_str, entries in entries_by_date.items():
        for e in entries:
            result.append({**e, "_mock_date": day_str})
    return result


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def extract_trends(
    price_guide: list[dict],
    targets: dict[str, str],
    override_date: str | None = None,
) -> dict[str, tuple[float, str]]:
    """Return {idProduct_str: (trend, date)} for every tracked product."""
    target_ids = {int(k) for k in targets}
    trends: dict[str, tuple[float, str]] = {}
    for entry in price_guide:
        pid = entry.get("idProduct")
        if pid in target_ids:
            entry_date = entry.get("_mock_date", override_date or date.today().isoformat())
            trends[str(pid)] = (float(entry["trend"]), entry_date)
    return trends


def load_history(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_history(path: str, history: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def update_history(
    history: dict,
    trends: dict[str, tuple[float, str]],
    targets: dict[str, str],
) -> tuple[dict, int]:
    """
    Merge trends into history. Returns (updated_history, new_entry_count).

    JSON structure:
      {
        "812570": {
          "name": "...",
          "prices": [{"date": "2025-07-10", "trend": 8.13}, ...]
        }
      }
    Idempotent: skips any (product, date) pair already recorded.
    """
    new_count = 0
    for pid, (trend, entry_date) in trends.items():
        if pid not in history:
            history[pid] = {"name": targets[pid], "prices": []}
        existing_dates = {e["date"] for e in history[pid]["prices"]}
        if entry_date not in existing_dates:
            history[pid]["prices"].append({"date": entry_date, "trend": trend})
            history[pid]["prices"].sort(key=lambda e: e["date"])
            print(f"  + {targets[pid]}: {trend} € on {entry_date}")
            new_count += 1
        else:
            print(f"  ~ {targets[pid]}: already recorded for {entry_date}, skipped")
    return history, new_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mock_mode = "--mock" in sys.argv
    today = date.today().isoformat()

    print(f"Cardmarket Price Tracker — {today}")
    print(f"Mode: {'MOCK (90-day backfill)' if mock_mode else 'PRODUCTION'}")
    print()

    price_guide = fetch_price_guide_mock() if mock_mode else fetch_price_guide()

    history = load_history(PRICE_HISTORY_FILE)

    if mock_mode:
        # Mock data carries per-entry dates — process each entry individually
        for entry in price_guide:
            pid = str(entry.get("idProduct"))
            if pid in TARGETS:
                entry_date = entry["_mock_date"]
                existing_dates = {e["date"] for e in history.get(pid, {}).get("prices", [])}
                if entry_date not in existing_dates:
                    if pid not in history:
                        history[pid] = {"name": TARGETS[pid], "prices": []}
                    history[pid]["prices"].append({"date": entry_date, "trend": entry["trend"]})
        for pid in TARGETS:
            if pid in history:
                history[pid]["prices"].sort(key=lambda e: e["date"])
        total = sum(len(history[p]["prices"]) for p in TARGETS if p in history)
        print(f"  Mock backfill complete — {total} total entries written.")
    else:
        trends = extract_trends(price_guide, TARGETS, today)
        missing = [name for pid, name in TARGETS.items() if pid not in trends]
        if missing:
            print(f"WARNING: no data found for: {', '.join(missing)}")
        history, new_count = update_history(history, trends, TARGETS)
        print()
        print(f"price_history.json updated ({new_count} new entry/entries recorded).")

    save_history(PRICE_HISTORY_FILE, history)


if __name__ == "__main__":
    main()
