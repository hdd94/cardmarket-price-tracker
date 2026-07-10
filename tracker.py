import json
import math
import os
import random
import sys
from datetime import date, timedelta

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGETS: dict[str, str] = {
    "803869": "Aetherdrift Collector Booster Box",
    "813080": "Tarkir: Dragonstorm Collector Booster Box",
    "812573": "Magic: The Gathering — FINAL FANTASY Collector Booster Box",
    "813293": "Edge of Eternities Collector Booster Box",
    "814380": "Magic: The Gathering | Marvel's Spider-Man Collector Booster Box",
    "842564": "Magic: The Gathering | Avatar: The Last Airbender Collector Booster Box",
    "851271": "Lorwyn Eclipsed Collector Booster Box",
    "853671": "Magic: The Gathering | Teenage Mutant Ninja Turtles Collector Booster Box",
    "869357": "Secrets of Strixhaven Collector Booster Box",
    "869496": "Magic: The Gathering | Marvel Super Heroes Collector Booster Box",
    "885552": "The Hobbit Collector Booster Box",
}

PRICE_HISTORY_FILE = "price_history.json"

PRICE_GUIDE_URL = (
    "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
)

# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_price_guide() -> list[dict]:
    response = requests.get(PRICE_GUIDE_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return payload.get("priceGuides", [])
    return payload


def fetch_price_guide_mock() -> list[dict]:
    """90-day realistic backfill for local testing — generates trend/avg/low."""
    base_prices = {
        803869: 208.0,
        813080: 346.0,
        812573: 910.0,
        813293: 456.0,
        814380: 299.0,
        842564: 313.0,
        851271: 306.0,
        853671: 279.0,
        869357: 317.0,
        869496: 297.0,
        885552: 566.0,
    }

    today = date.today()
    result = []
    for days_ago in range(89, -1, -1):
        day_str = (today - timedelta(days=days_ago)).isoformat()
        for pid, base in base_prices.items():
            t = days_ago / 30.0
            drift = base * 0.12 * math.sin(t * math.pi)
            trend = round(max(base * 0.6, base + drift + random.uniform(-0.03, 0.03) * base), 2)
            avg   = round(trend * random.uniform(0.96, 1.04), 2)
            low   = round(trend * random.uniform(0.80, 0.95), 2)
            result.append({
                "idProduct": pid,
                "idCategory": 2,
                "trend": trend,
                "avg": avg,
                "low": low,
                "_mock_date": day_str,
            })
    return result


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def extract_prices(
    price_guide: list[dict],
    targets: dict[str, str],
    today: str,
) -> dict[str, dict]:
    """
    Return {pid_str: {"trend": float, "avg": float|None, "low": float|None, "date": str}}
    for every tracked product found in the guide.
    """
    target_ids = {int(k) for k in targets}
    out: dict[str, dict] = {}
    for entry in price_guide:
        pid = entry.get("idProduct")
        if pid in target_ids:
            entry_date = entry.get("_mock_date", today)
            out[str(pid)] = {
                "date":  entry_date,
                "trend": float(entry["trend"]) if entry.get("trend") is not None else None,
                "avg":   float(entry["avg"])   if entry.get("avg")   is not None else None,
                "low":   float(entry["low"])   if entry.get("low")   is not None else None,
            }
    return out


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
    prices: dict[str, dict],
    targets: dict[str, str],
) -> tuple[dict, int]:
    """
    Merge today's prices into history. Idempotent — skips existing dates.

    JSON structure per product:
      {
        "name": "...",
        "prices": [
          {"date": "2026-07-10", "trend": 909.98, "avg": 796.88, "low": 679.99},
          ...
        ]
      }
    """
    new_count = 0
    for pid, data in prices.items():
        entry_date = data["date"]
        if pid not in history:
            history[pid] = {"name": targets[pid], "prices": []}
        existing_dates = {e["date"] for e in history[pid]["prices"]}
        if entry_date not in existing_dates:
            history[pid]["prices"].append({
                "date":  entry_date,
                "trend": data["trend"],
                "avg":   data["avg"],
                "low":   data["low"],
            })
            history[pid]["prices"].sort(key=lambda e: e["date"])
            t = data["trend"]
            a = data["avg"]
            l = data["low"]
            print(f"  + {targets[pid]}")
            print(f"      trend={t} € | avg={a} € | low={l} € | {entry_date}")
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
        for entry in price_guide:
            pid = str(entry.get("idProduct"))
            if pid not in TARGETS:
                continue
            entry_date = entry["_mock_date"]
            if pid not in history:
                history[pid] = {"name": TARGETS[pid], "prices": []}
            existing = {e["date"] for e in history[pid]["prices"]}
            if entry_date not in existing:
                history[pid]["prices"].append({
                    "date":  entry_date,
                    "trend": entry["trend"],
                    "avg":   entry["avg"],
                    "low":   entry["low"],
                })
        for pid in TARGETS:
            if pid in history:
                history[pid]["prices"].sort(key=lambda e: e["date"])
        total = sum(len(history[p]["prices"]) for p in TARGETS if p in history)
        print(f"  Mock backfill complete — {total} total entries written.")
    else:
        prices = extract_prices(price_guide, TARGETS, today)
        missing = [name for pid, name in TARGETS.items() if pid not in prices]
        if missing:
            print(f"WARNING: no data found for: {', '.join(missing)}")
        history, new_count = update_history(history, prices, TARGETS)
        print()
        print(f"price_history.json updated ({new_count} new entry/entries recorded).")

    save_history(PRICE_HISTORY_FILE, history)


if __name__ == "__main__":
    main()
