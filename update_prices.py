#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.38", "pandas>=2.0"]
# ///
"""
update_prices.py — fetch live prices for watchlist + all IPO tickers, write to data.js
Run from the singhvp.github.io folder:
  uv run update_prices.py
  uv run update_prices.py --deploy   # also pushes to GitHub via deploy.sh
"""

import json, re, sys, subprocess, os, shutil, tempfile
from datetime import datetime
from pathlib import Path

import yfinance as yf
import pandas as pd

# ── Wipe yfinance cache to avoid SQLite corruption ───────────────────────────
_cache = os.path.join(tempfile.gettempdir(), "yf_portfolio_cache")
shutil.rmtree(_cache, ignore_errors=True)
os.makedirs(_cache, exist_ok=True)
yf.set_tz_cache_location(_cache)

BASE = Path(__file__).parent

# ── Watchlist tickers ─────────────────────────────────────────────────────────
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

# ── IPO tickers ───────────────────────────────────────────────────────────────
IPO_TICKERS = [
    "AEGISVOPAK.NS","SCHLOSS.NS","PROSTARM.NS","SCODAT.NS","ARISINFRA.NS",
    "KALPATARULD.NS","ELLENBARRIE.NS","GLOBECIVIL.NS","HDBFS.NS","SAMBHVSTEEL.NS",
    "INDOGULF.NS","CRIZAC.NS","TRAVELFOOD.NS","SMARTWORKS.NS","ANTHEMBIOSCIENCES.NS",
    "GNGELECTRONIC.NS","INDIQUBE.NS","BRIGADEHVL.NS","LAXMIIND.NS","ADITYAINFO.NS",
    "MBENG.NS","NSDL.BO","SRILOTUS.NS","HIGHWAYINFRA.NS","JSWCEMENT.NS",
    "ALLTIMEPLASTIC.NS","BLUESTONE.NS","KRT.NS","PACEDIGTECH.NS","GLOTTIS.NS",
    "FABTECH.NS","OMFRIEGHT.NS","WEWORK.NS","ADVANCEAGRO.NS","TATACAP.NS",
    "LGEINDIA.NS","CRAMC.NS","RUBICON.NS","ANANTAM.NS","CANHLIFE.NS",
    "LENSKART.NS","GROWW.NS","PINELABS.NS","PWL.NS","EMMVEE.NS",
    "TENNECO.NS","FUJIYAMA.NS","CAPILLARYTEC.NS","EXCELSOFT.NS","SUDEEPPHARMA.NS",
    "MEESHO.NS","ICICIAMC.NS","BHARATCOAL.NS","AMAGI.NS","SHADOWFAX.NS",
    "FRACTAL.NS","AYEF.NS","GAUDIUMIVF.NS","SRTL.NS","CLEANMAX.NS",
    "PNGSREVA.NS","OMNITECH.NS","SEDEMAC.NS","RJPS.NS","INNOVISION.NS",
    "RAAJMARG.NS","GSPCROPSC.NS","CMPDI.NS","AMIRCHAND.NS","POWERICA.NS",
    "SAIPAREN.NS","OMPOWER.NS","CITIUSTRANS.NS","ONEMI.NS","BAGMANE.NS",
    "CMRGREEN.NS","HEXANUT.NS",
]


def batch_prices(tickers, label):
    """Batch-download 1Y OHLC; return dict ticker → {cmp, high52, low52}."""
    print(f"\n📥 Batch-downloading {len(tickers)} {label} tickers...")
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
            print(f"  ✓  {ticker:<25} ₹{out[ticker]['cmp']:>9.2f}")
        except Exception as e:
            print(f"  ⚠  {ticker:<25} {str(e)[:50]}")
    print(f"  → {len(out)}/{len(tickers)} fetched")
    return out


def read_sectors_block(data_js_path):
    content = data_js_path.read_text()
    m = re.search(r'(sectors:\s*\{.*?\n  \})', content, re.DOTALL)
    return m.group(1) if m else 'sectors: { updated: "—", themes: [] }'


def read_ipos_block(data_js_path):
    content = data_js_path.read_text()
    m = re.search(r'(ipos:\s*\{.*?\n  \})', content, re.DOTALL)
    return m.group(1) if m else None


def update_ipo_prices_in_block(ipos_block, ipo_price_map):
    """Patch cmp/high52/low52/vsIpo inside the JS ipos block."""
    def patch_entry(match):
        obj = match.group(0)
        tm = re.search(r'ticker:\s*"([^"]+)"', obj)
        if not tm:
            return obj
        ticker = tm.group(1)
        p = ipo_price_map.get(ticker)
        if not p:
            return obj

        cmp, h52, l52 = p["cmp"], p["high52"], p["low52"]

        lom = re.search(r'offerLow:\s*([\d.]+)', obj)
        him = re.search(r'offerHigh:\s*([\d.]+)', obj)
        vs_ipo = "null"
        if lom and him:
            mid = (float(lom.group(1)) + float(him.group(1))) / 2
            if mid > 0:
                vs_ipo = str(round((cmp - mid) / mid * 100, 1))

        obj = re.sub(r'cmp:\s*(?:null|\d+\.?\d*)',    f'cmp: {cmp}', obj)
        obj = re.sub(r'high52:\s*(?:null|\d+\.?\d*)', f'high52: {h52}', obj)
        obj = re.sub(r'low52:\s*(?:null|\d+\.?\d*)',  f'low52: {l52}', obj)
        obj = re.sub(r'vsIpo:\s*(?:null|-?\d+\.?\d*)',f'vsIpo: {vs_ipo}', obj)
        return obj

    return re.sub(r'\{[^{}]*ticker:[^{}]*\}', patch_entry, ipos_block, flags=re.DOTALL)


def write_data_js(data_js_path, watchlist_prices, ipo_prices):
    updated = datetime.now().strftime("%-d %b %Y, %I:%M %p")

    wl_lines = []
    for s in WATCHLIST:
        p = watchlist_prices.get(s["ns"])
        cmp_val = str(p["cmp"]) if p else "null"
        wl_lines.append(f'      {{ ticker: "{s["ticker"]}", name: "{s["name"]}", cmp: {cmp_val} }}')
    wl_block = ",\n".join(wl_lines)

    sectors_block = read_sectors_block(data_js_path)

    ipos_block = read_ipos_block(data_js_path)
    if ipos_block:
        ipos_block = update_ipo_prices_in_block(ipos_block, ipo_prices)
        ipos_block = re.sub(r'updated:\s*"[^"]+"', f'updated: "{updated}"', ipos_block, count=1)
    else:
        ipos_block = 'ipos: { updated: "—", listed: [], upcoming: [] }'

    content = f"""// data.js — auto-updated by update_prices.py
// Do not edit manually

window.PORTFOLIO_DATA = {{

  watchlist: {{
    updated: "{updated}",
    stocks: [
{wl_block}
    ]
  }},

  {sectors_block},

  {ipos_block}

}};
"""
    data_js_path.write_text(content)
    print(f"\n✅  data.js updated — {updated}")


def main():
    deploy = "--deploy" in sys.argv
    data_js = BASE / "data.js"

    wl_tickers = [s["ns"] for s in WATCHLIST]
    wl_prices = batch_prices(wl_tickers, "watchlist")
    ipo_prices = batch_prices(IPO_TICKERS, "IPO")

    write_data_js(data_js, wl_prices, ipo_prices)

    if deploy:
        print("\n🚀 Running deploy.sh...")
        subprocess.run(["bash", str(BASE / "deploy.sh")], check=True)
    else:
        print("\nRun with --deploy to push to GitHub:")
        print("  uv run update_prices.py --deploy")


if __name__ == "__main__":
    main()
