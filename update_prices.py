#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.38", "pandas>=2.0"]
# ///
"""
update_prices.py — fetch live prices for watchlist + IPO tickers, write to data.js
Source of truth for IPOs: ../ipo_tracker_data.json

Run from singhvp.github.io folder:
  uv run update_prices.py
  uv run update_prices.py --deploy
"""

import csv, io, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, zipfile
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

# ── Wipe yfinance cache to avoid SQLite corruption ────────────────────────────
_cache = os.path.join(tempfile.gettempdir(), "yf_portfolio_cache")
shutil.rmtree(_cache, ignore_errors=True)
os.makedirs(_cache, exist_ok=True)
yf.set_tz_cache_location(_cache)

BASE      = Path(__file__).parent
IPO_JSON  = BASE / "ipo_tracker_data.json"

# ── Watchlist ─────────────────────────────────────────────────────────────────
WATCHLIST = [
    {"ticker": "ADANIPORTS", "name": "Adani Ports",                "ns": "ADANIPORTS.NS"},
    {"ticker": "ASTRAMICRO", "name": "Astra Microwave",            "ns": "ASTRAMICRO.NS"},
    {"ticker": "GPIL",       "name": "Godawari Power & Ispat",     "ns": "GPIL.NS"},
    {"ticker": "PAYTM",      "name": "Paytm",                      "ns": "PAYTM.NS"},
    {"ticker": "HBLENGINE",  "name": "HBL Engineering",            "ns": "HBLENGINE.NS"},
    {"ticker": "KRISHNADEF", "name": "Krishna Defence",            "ns": "KRISHNADEF.NS"},
    {"ticker": "ZENTEC",     "name": "Zen Technologies",           "ns": "ZENTEC.NS"},
    {"ticker": "MEDIASSIST", "name": "Medi Assist",                "ns": "MEDIASSIST.NS"},
    {"ticker": "UNIMECH",    "name": "Unimech Aerospace",          "ns": "UNIMECH.NS"},
    {"ticker": "GOLDCASE",   "name": "Goldcase",                   "ns": "GOLDCASE.NS"},
    {"ticker": "FEDFINA",    "name": "Federal Bank Fin. Services", "ns": "FEDFINA.NS"},
    {"ticker": "EMMFORCE",   "name": "Emmforce Autotech",          "ns": "EMMFORCE.NS"},
    {"ticker": "INTELLECT",  "name": "Intellect Design Arena",     "ns": "INTELLECT.NS"},
    {"ticker": "RATEGAIN",   "name": "RateGain Travel Tech",       "ns": "RATEGAIN.NS"},
    {"ticker": "NSDL",       "name": "NSDL",                       "ns": "NSDL.BO"},
    {"ticker": "NH",         "name": "Narayana Hrudayalaya",       "ns": "NH.NS"},
    {"ticker": "BDL",        "name": "Bharat Dynamics",            "ns": "BDL.NS"},
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def batch_prices(tickers, label):
    """yfinance batch download. Returns dict ticker → {cmp, high52, low52}."""
    print(f"\n📥 Batch-fetching {len(tickers)} {label} tickers via yfinance...")
    raw = yf.download(
        tickers=tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=True,
        threads=4,
    )
    out = {}
    for ticker in tickers:
        try:
            df = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue
            out[ticker] = {
                "cmp":    round(float(df["Close"].iloc[-1]), 2),
                "high52": round(float(df["High"].max()), 2),
                "low52":  round(float(df["Low"].min()), 2),
            }
        except Exception:
            pass
    hits = len(out)
    print(f"  → {hits}/{len(tickers)} fetched")
    for t, p in out.items():
        print(f"    ✓  {t:<28} ₹{p['cmp']:>9.2f}")
    return out


def nse_bhavcopy_prices(missing_symbols):
    """
    Fallback: fetch NSE daily bhavcopy for symbols yfinance missed.
    Returns dict NSE_SYMBOL → close price (no 52W H/L).
    Tries last 5 trading days, two URL formats.
    """
    if not missing_symbols:
        return {}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }

    # Last 5 trading days
    dates = []
    d = datetime.today()
    while len(dates) < 5:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)

    sym_map = {}   # NSE_SYMBOL → close price

    for dt in dates:
        dd   = dt.strftime("%d%m%Y")   # DDMMYYYY
        ymd  = dt.strftime("%Y%m%d")   # YYYYMMDD

        url_candidates = [
            # New full bhavcopy CSV
            f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dd}.csv",
            # New CM bhavcopy ZIP
            f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
        ]

        for url in url_candidates:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()

                if url.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        fname = next(n for n in z.namelist() if n.endswith(".csv"))
                        content = io.TextIOWrapper(z.open(fname), encoding="utf-8")
                        reader = csv.DictReader(content)
                        for row in reader:
                            sym   = (row.get("SYMBOL") or row.get("Symbol") or "").strip()
                            close = (row.get("CLOSE") or row.get("CLOSE_PRICE") or row.get("Close") or "").strip()
                            if sym and close:
                                try: sym_map[sym] = float(close.replace(",", ""))
                                except ValueError: pass
                else:
                    reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
                    for row in reader:
                        sym   = (row.get("SYMBOL") or row.get("Symbol") or "").strip()
                        close = (row.get("CLOSE") or row.get("CLOSE_PRICE") or row.get("Close") or "").strip()
                        if sym and close:
                            try: sym_map[sym] = float(close.replace(",", ""))
                            except ValueError: pass

                if sym_map:
                    print(f"\n  📋 NSE bhavcopy loaded ({dt.strftime('%d %b')}): {len(sym_map)} symbols")
                    break

            except Exception as e:
                print(f"  ⚠  NSE bhavcopy {url[50:]}: {e}")

        if sym_map:
            break

    if not sym_map:
        print("  ✗  NSE bhavcopy unavailable — all URLs failed")
        return {}

    # Match missing tickers to bhavcopy symbols
    result = {}
    for ticker in missing_symbols:
        sym = ticker.replace(".NS", "").replace(".BO", "")
        if sym in sym_map:
            result[ticker] = {
                "cmp":    round(sym_map[sym], 2),
                "high52": None,
                "low52":  None,
            }
            print(f"    ✓  {ticker:<28} ₹{sym_map[sym]:>9.2f}  (bhavcopy)")

    missed = [t for t in missing_symbols if t not in result]
    if missed:
        print(f"  Still missing after bhavcopy ({len(missed)}): {', '.join(missed[:8])}{'…' if len(missed)>8 else ''}")
    return result


def load_ipos():
    """
    Load IPO list from ipo_tracker_data.json.
    Returns (listed, upcoming) as lists of dicts.
    """
    with open(IPO_JSON) as f:
        raw = json.load(f)

    today_str = datetime.today().strftime("%d %b %Y")
    today     = datetime.today()

    listed, upcoming = [], []
    for ipo in raw:
        ticker = ipo.get("ticker")
        if not ticker:
            continue

        ld = ipo.get("listingDate", "")
        try:
            listing_dt = datetime.strptime(ld, "%d %b %Y")
            is_listed  = listing_dt.date() <= today.date()
        except ValueError:
            is_listed = True

        entry = {
            "name":        ipo["name"],
            "ticker":      ticker,
            "offerLow":    ipo.get("offerPriceLow"),
            "offerHigh":   ipo.get("offerPriceHigh"),
            "listingDate": ld,
            "listingClose": ipo.get("listingClose"),
            "cmp":         None,
            "high52":      None,
            "low52":       None,
            "vsIpo":       None,
            "business":    ipo.get("business", ""),
            "moat":        ipo.get("moat", ""),
        }

        if is_listed:
            listed.append(entry)
        else:
            upcoming.append(entry)

    return listed, upcoming


def apply_prices(entries, price_map):
    """Patch cmp/high52/low52/vsIpo into entry dicts."""
    for e in entries:
        p = price_map.get(e["ticker"])
        if not p:
            continue
        e["cmp"]    = p["cmp"]
        e["high52"] = p.get("high52")
        e["low52"]  = p.get("low52")
        lo = e.get("offerLow")
        hi = e.get("offerHigh")
        if e["cmp"] and lo and hi:
            mid = (lo + hi) / 2
            if mid > 0:
                e["vsIpo"] = round((e["cmp"] - mid) / mid * 100, 1)


def js_val(v):
    if v is None:
        return "null"
    if isinstance(v, str):
        # Escape backslash and double-quote, then wrap
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, float):
        return str(round(v, 2))
    return str(v)


def ipo_to_js(e, indent="      "):
    fields = [
        f'name: {js_val(e["name"])}',
        f'ticker: {js_val(e["ticker"])}',
        f'offerLow: {js_val(e["offerLow"])}',
        f'offerHigh: {js_val(e["offerHigh"])}',
        f'listingDate: {js_val(e["listingDate"])}',
        f'listingClose: {js_val(e["listingClose"])}',
        f'cmp: {js_val(e["cmp"])}',
        f'high52: {js_val(e["high52"])}',
        f'low52: {js_val(e["low52"])}',
        f'vsIpo: {js_val(e["vsIpo"])}',
        f'business: {js_val(e["business"])}',
        f'moat: {js_val(e["moat"])}',
    ]
    inner = f",\n{indent}  ".join(fields)
    return f"{indent}{{ {inner} }}"


def read_sectors_block(data_js_path):
    content = data_js_path.read_text()
    m = re.search(r'(sectors:\s*\{.*?\n  \})', content, re.DOTALL)
    return m.group(1) if m else 'sectors: { updated: "—", themes: [] }'


def write_data_js(data_js_path, wl_prices, ipo_prices, listed, upcoming):
    updated = datetime.now().strftime("%-d %b %Y, %I:%M %p")

    # Apply prices
    apply_prices(listed, ipo_prices)
    apply_prices(upcoming, ipo_prices)

    # Watchlist block
    wl_lines = []
    for s in WATCHLIST:
        p = wl_prices.get(s["ns"])
        cmp_val = str(p["cmp"]) if p else "null"
        wl_lines.append(f'      {{ ticker: "{s["ticker"]}", name: "{s["name"]}", cmp: {cmp_val} }}')

    # IPO blocks
    listed_js   = ",\n".join(ipo_to_js(e) for e in listed)
    upcoming_js = ",\n".join(ipo_to_js(e) for e in upcoming)

    sectors_block = read_sectors_block(data_js_path)

    content = f"""// data.js — auto-updated by update_prices.py
// Do not edit manually

window.PORTFOLIO_DATA = {{

  watchlist: {{
    updated: "{updated}",
    stocks: [
{(",\n").join(wl_lines)}
    ]
  }},

  {sectors_block},

  ipos: {{
    updated: "{updated}",
    listed: [
{listed_js}
    ],
    upcoming: [
{upcoming_js}
    ]
  }}

}};
"""
    data_js_path.write_text(content)

    priced_listed = sum(1 for e in listed if e["cmp"] is not None)
    print(f"\n✅  data.js written — {updated}")
    print(f"   Watchlist: {sum(1 for s in WATCHLIST if wl_prices.get(s['ns']))}/{len(WATCHLIST)} priced")
    print(f"   IPOs listed: {priced_listed}/{len(listed)} priced  |  upcoming: {len(upcoming)}")


def main():
    deploy    = "--deploy" in sys.argv
    data_js   = BASE / "data.js"

    listed, upcoming = load_ipos()
    print(f"Loaded {len(listed)} listed + {len(upcoming)} upcoming IPOs from JSON")

    # ── Step 1: yfinance batch ────────────────────────────────────────────────
    wl_tickers  = [s["ns"] for s in WATCHLIST]
    ipo_tickers = [e["ticker"] for e in listed + upcoming]

    wl_prices  = batch_prices(wl_tickers, "watchlist")
    ipo_prices = batch_prices(ipo_tickers, "IPO")

    # ── Step 2: NSE bhavcopy for IPO misses ───────────────────────────────────
    missing = [t for t in ipo_tickers if t not in ipo_prices]
    print(f"\n🔍 {len(missing)} IPO tickers not found in yfinance — trying NSE bhavcopy...")
    bhav = nse_bhavcopy_prices(missing)
    ipo_prices.update(bhav)

    # ── Step 3: NSE bhavcopy for watchlist misses ─────────────────────────────
    wl_missing = [s["ns"] for s in WATCHLIST if s["ns"] not in wl_prices]
    if wl_missing:
        print(f"\n🔍 {len(wl_missing)} watchlist tickers not in yfinance — trying NSE bhavcopy...")
        wl_bhav = nse_bhavcopy_prices(wl_missing)
        wl_prices.update(wl_bhav)

    # ── Step 4: Write data.js ─────────────────────────────────────────────────
    write_data_js(data_js, wl_prices, ipo_prices, listed, upcoming)

    if deploy:
        print("\n🚀 Running deploy.sh...")
        subprocess.run(["bash", str(BASE / "deploy.sh")], check=True)
    else:
        print("\nRun with --deploy to push to GitHub:")
        print("  uv run update_prices.py --deploy")


if __name__ == "__main__":
    main()
