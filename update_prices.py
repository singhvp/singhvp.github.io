#!/usr/bin/env python3
"""
update_prices.py — fetch live NSE prices and write to data.js
Run from the singhvp.github.io folder:
  python3 update_prices.py
  python3 update_prices.py --deploy   # also runs deploy.sh after updating
"""

import json
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# --- Stock list ---
STOCKS = [
    {"ticker": "ADANIPORTS",  "name": "Adani Ports",                "ns": "ADANIPORTS.NS"},
    {"ticker": "ASTRAMICRO",  "name": "Astra Microwave",            "ns": "ASTRAMICRO.NS"},
    {"ticker": "GPIL",        "name": "Godawari Power & Ispat",     "ns": "GPIL.NS"},
    {"ticker": "PAYTM",       "name": "Paytm",                      "ns": "PAYTM.NS"},
    {"ticker": "HBLENGINE",   "name": "HBL Engineering",            "ns": "HBLENGINE.NS"},
    {"ticker": "KRISHNADEF",  "name": "Krishna Defence",            "ns": "KRISHNADEF.NS"},
    {"ticker": "ZENTEC",      "name": "Zen Technologies",           "ns": "ZENTEC.NS"},
    {"ticker": "MEDIASSIST",  "name": "Medi Assist",                "ns": "MEDIASSIST.NS"},
    {"ticker": "UNIMECH",     "name": "Unimech Aerospace",          "ns": "UNIMECH.NS"},
    {"ticker": "GOLDCASE",    "name": "Goldcase",                   "ns": "GOLDCASE.NS"},
    {"ticker": "FEDFINA",     "name": "Federal Bank Fin. Services", "ns": "FEDFINA.NS"},
    {"ticker": "EMMFORCE",    "name": "Emmforce Autotech",          "ns": "EMMFORCE.NS"},
    {"ticker": "INTELLECT",   "name": "Intellect Design Arena",     "ns": "INTELLECT.NS"},
    {"ticker": "RATEGAIN",    "name": "RateGain Travel Tech",       "ns": "RATEGAIN.NS"},
    {"ticker": "NSDL",        "name": "NSDL",                       "ns": "NSDL.NS"},
    {"ticker": "NH",          "name": "Narayana Hrudayalaya",       "ns": "NH.NS"},
    {"ticker": "BDL",         "name": "Bharat Dynamics",            "ns": "BDL.NS"},
]

def fetch_prices():
    import requests

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    print("Fetching prices from Yahoo Finance...")
    price_map = {}
    session = requests.Session()

    for s in STOCKS:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s['ns']}?interval=1d&range=1d"
        try:
            r = session.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            meta = data["chart"]["result"][0]["meta"]
            price = round(float(meta.get("regularMarketPrice") or meta.get("previousClose")), 2)
        except Exception:
            price = None
        price_map[s["ticker"]] = price
        status = f"Rs.{price:,.2f}" if price else "—"
        print(f"  {s['ticker']:15s} {status}")

    return price_map


def read_current_data(data_js_path):
    """Extract the current sectors block from data.js so we don't overwrite it."""
    content = data_js_path.read_text()
    # Extract sectors JSON between sectors: { ... } — grab the full object
    match = re.search(r'sectors:\s*(\{.*?\n  \})', content, re.DOTALL)
    if match:
        return match.group(0)
    return None


def write_data_js(data_js_path, price_map, sectors_block):
    updated = datetime.now().strftime("%-d %b %Y, %I:%M %p")

    stocks_js = []
    for s in STOCKS:
        cmp = price_map.get(s["ticker"])
        cmp_val = str(cmp) if cmp is not None else "null"
        stocks_js.append(
            f'      {{ ticker: "{s["ticker"]}", name: "{s["name"]}", cmp: {cmp_val} }}'
        )

    stocks_block = ",\n".join(stocks_js)

    content = f"""// data.js — auto-updated by update_prices.py
// Do not edit manually

window.PORTFOLIO_DATA = {{

  watchlist: {{
    updated: "{updated}",
    stocks: [
{stocks_block}
    ]
  }},

  {sectors_block}

}};
"""
    data_js_path.write_text(content)
    print(f"\n✅ data.js updated — {updated}")


def main():
    deploy = "--deploy" in sys.argv
    base = Path(__file__).parent
    data_js = base / "data.js"

    price_map = fetch_prices()
    sectors_block = read_current_data(data_js) or 'sectors: { updated: "—", themes: [] }'
    write_data_js(data_js, price_map, sectors_block)

    if deploy:
        print("\n🚀 Running deploy.sh...")
        subprocess.run(["bash", str(base / "deploy.sh")], check=True)
    else:
        print("\nRun with --deploy to push to GitHub automatically:")
        print("  python3 update_prices.py --deploy")


if __name__ == "__main__":
    main()
