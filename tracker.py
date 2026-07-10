import json
import os
import sys
from datetime import date

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

# Cardmarket Price Guide endpoint
# The real URL — adjust if the public dump URL changes in the future.
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
    """Return a simulated Price Guide payload for local testing."""
    return [
        {"idProduct": 812570, "idCategory": 2, "trend": 8.13},
        {"idProduct": 794120, "idCategory": 2, "trend": 124.50},
        {"idProduct": 775932, "idCategory": 2, "trend": 97.20},
        {"idProduct": 999999, "idCategory": 2, "trend": 5.00},   # not tracked — ignored
    ]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def extract_trends(
    price_guide: list[dict],
    targets: dict[str, str],
) -> dict[str, float]:
    """Return {idProduct_str: trend} for every tracked product found in the guide."""
    target_ids = {int(k) for k in targets}
    trends: dict[str, float] = {}
    for entry in price_guide:
        pid = entry.get("idProduct")
        if pid in target_ids:
            trends[str(pid)] = float(entry["trend"])
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
    trends: dict[str, float],
    targets: dict[str, str],
    today: str,
) -> dict:
    """
    Merge today's trends into the history dict.
    Structure:
      {
        "812570": {
          "name": "Duskmourn Collector Booster Display",
          "prices": [
            {"date": "2025-07-10", "trend": 8.13},
            ...
          ]
        },
        ...
      }
    Skips a product if today's entry already exists (idempotent re-runs).
    """
    for pid, trend in trends.items():
        if pid not in history:
            history[pid] = {"name": targets[pid], "prices": []}
        existing_dates = {entry["date"] for entry in history[pid]["prices"]}
        if today not in existing_dates:
            history[pid]["prices"].append({"date": today, "trend": trend})
            print(f"  + {targets[pid]}: {trend} € on {today}")
        else:
            print(f"  ~ {targets[pid]}: already recorded for {today}, skipped")
    return history


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mock_mode = "--mock" in sys.argv
    today = date.today().isoformat()

    print(f"Cardmarket Price Tracker — {today}")
    print(f"Mode: {'MOCK' if mock_mode else 'PRODUCTION'}")
    print()

    price_guide = fetch_price_guide_mock() if mock_mode else fetch_price_guide()
    trends = extract_trends(price_guide, TARGETS)

    missing = [name for pid, name in TARGETS.items() if pid not in trends]
    if missing:
        print(f"WARNING: no data found for: {', '.join(missing)}")

    history = load_history(PRICE_HISTORY_FILE)
    history = update_history(history, trends, TARGETS, today)
    save_history(PRICE_HISTORY_FILE, history)

    print()
    print(f"price_history.json updated ({len(trends)} product(s) recorded).")


if __name__ == "__main__":
    main()
