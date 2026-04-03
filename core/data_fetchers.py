import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import logging
import time
import urllib.request
import json
from datetime import datetime, timedelta, date
from io import StringIO
import re
from core import now_cdmx

PARQUET_PATH = "data/master.parquet"

@st.cache_resource
def check_playwright_installed() -> bool:
    """
    Instala Chromium si no existe y verifica que funcione.
    Se ejecuta UNA sola vez por deployment (cache_resource).
    """
    log = logging.getLogger("vix_controller")
    try:
        import subprocess
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log.info("Playwright install chromium: OK")
        else:
            log.warning(f"Playwright install output: {result.stderr[:300]}")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
            )
            browser.close()
        log.info("Playwright check: Chromium OK")
        return True
    except Exception as e:
        log.error(f"Playwright check failed: {e}")
        return False

pw_ready = check_playwright_installed()

@st.cache_data(ttl=55)
def scrape_cboe_futures() -> pd.DataFrame:
    """
    Lanza Chromium, scrapea, cierra — todo en el mismo thread.
    Cache de 55s evita relanzar el browser en cada rerun de Streamlit.
    El check_playwright_installed() ya validó que Chromium existe.
    """
    log = logging.getLogger("vix_controller")

    if not pw_ready:
        log.error("CBOE_SCRAPE: Playwright no disponible")
        st.session_state["scrape_debug"] = "❌ Playwright/Chromium no instalado"
        return pd.DataFrame()

    from playwright.sync_api import sync_playwright

    html = ""
    try:
        log.info("CBOE_SCRAPE: lanzando Chromium...")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                      '--disable-extensions', '--no-first-run'],
            )
            page = browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
            )
            # Bloquear solo trackers — no CSS ni JS de CBOE
            page.route("**/googletagmanager**", lambda r: r.abort())
            page.route("**/google-analytics**", lambda r: r.abort())
            page.route("**/doubleclick**",       lambda r: r.abort())

            log.info("CBOE_SCRAPE: navegando...")
            page.goto(
                'https://www.cboe.com/delayed_quotes/futures/future_quotes',
                wait_until='networkidle', timeout=45000
            )

            # Esperar texto VX/ en página
            try:
                page.wait_for_function(
                    "() => document.body.innerText.includes('VX/')",
                    timeout=25000
                )
                log.info("CBOE_SCRAPE: VX/ detectado ✅")
            except Exception:
                log.warning("CBOE_SCRAPE: VX/ no apareció en 25s — tomando HTML igual")

            html = page.content()
            browser.close()

        vx_n = html.count('VX/')
        log.info(f"CBOE_SCRAPE: HTML {len(html):,} chars · VX/ hits: {vx_n}")
        st.session_state["scrape_debug"] = (
            f"HTML: {len(html):,} chars · 'VX/' en HTML: {vx_n} · "
            f"{now_cdmx().strftime('%H:%M:%S')}"
        )

    except Exception as e:
        log.error(f"CBOE_SCRAPE: error — {e}")
        st.session_state["scrape_debug"] = f"❌ Error: {e}"
        return pd.DataFrame()

    # Parsear tablas HTML
    try:
        all_tables = pd.read_html(StringIO(html))
        log.info(f"CBOE_SCRAPE: {len(all_tables)} tablas en HTML")
    except Exception as e:
        log.error(f"CBOE_SCRAPE: read_html error — {e}")
        st.session_state["scrape_debug"] += f" | read_html error: {e}"
        return pd.DataFrame()

    df_vx = pd.DataFrame()
    table_info = []
    for i, df in enumerate(all_tables):
        cols_upper = [str(c).upper().strip() for c in df.columns]
        table_info.append(f"T{i}:{cols_upper[:4]}")
        if 'SYMBOL' in cols_upper and 'EXPIRATION' in cols_upper:
            sym_col = df.columns[cols_upper.index('SYMBOL')]
            if df[sym_col].astype(str).str.startswith('VX').any():
                df_vx = df.copy()
                log.info(f"CBOE_SCRAPE: tabla VX en índice {i} ✅")
                break

    st.session_state["scrape_debug"] += f" | {len(all_tables)} tables: {' '.join(table_info[:4])}"

    if df_vx.empty:
        log.warning("CBOE_SCRAPE: tabla VX no encontrada")
        st.session_state["scrape_html_sample"] = html[1500:2500]
        return pd.DataFrame()

    df_vx.columns = [str(c).strip().upper() for c in df_vx.columns]
    rename = {
        'SYMBOL': 'Symbol', 'EXPIRATION': 'Expiration',
        'LAST': 'Last', 'CHANGE': 'Change',
        'HIGH': 'High', 'LOW': 'Low',
        'SETTLEMENT': 'Settlement', 'VOLUME': 'Volume',
    }
    df_vx.rename(columns={k: v for k, v in rename.items() if k in df_vx.columns}, inplace=True)

    if 'Symbol' in df_vx.columns:
        mask = df_vx['Symbol'].astype(str).str.match(r'^VX/[A-Z]\d+$')
        df_vx = df_vx[mask].reset_index(drop=True)

    if 'Expiration' in df_vx.columns:
        df_vx['Expiration'] = pd.to_datetime(df_vx['Expiration'], errors='coerce')
        df_vx = df_vx.sort_values('Expiration').reset_index(drop=True)

    for col in ['Last', 'Change', 'High', 'Low', 'Settlement', 'Volume']:
        if col in df_vx.columns:
            df_vx[col] = pd.to_numeric(
                df_vx[col].astype(str).str.replace(',', '', regex=False),
                errors='coerce'
            )

    today = pd.Timestamp(now_cdmx().date()).normalize()
    if 'Expiration' in df_vx.columns:
        df_vx['DTE'] = (df_vx['Expiration'] - today).dt.days

    df_vx['Price'] = df_vx.apply(
        lambda r: r['Last'] if pd.notna(r.get('Last')) and r.get('Last', 0) > 0
                  else r.get('Settlement', 0), axis=1
    )
    df_vx['Scraped_At'] = now_cdmx().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"CBOE_SCRAPE: {len(df_vx)} contratos mensuales ✅")
    return df_vx



@st.cache_data(ttl=55)
def fetch_vix_spot():
    try:
        h = yf.Ticker("^VIX").history(period="5d")
        if not h.empty:
            c = round(float(h['Close'].iloc[-1]), 2)
            p = round(float(h['Close'].iloc[-2]), 2) if len(h) > 1 else c
            return dict(price=c, prev=p, chg=round(c - p, 2))
    except: pass
    return None


@st.cache_data(ttl=55)
def fetch_etps():
    out = {}
    for name, sym in [("VXX","VXX"),("SVXY","SVXY"),("SVIX","SVIX"),("SPY","SPY")]:
        try:
            h = yf.Ticker(sym).history(period="5d")
            if not h.empty:
                out[name] = dict(
                    close=round(float(h['Close'].iloc[-1]), 2),
                    open=round(float(h['Open'].iloc[-1]), 2),
                    prev=round(float(h['Close'].iloc[-2]), 2) if len(h) > 1 else None,
                )
        except: continue
    return out

@st.cache_data(ttl=300)
def fetch_edge_extra():
    out = {}
    for name, sym in [("SKEW", "^SKEW"), ("HYG", "HYG"), ("IEF", "IEF")]:
        try:
            h = yf.download(sym, period="2y", progress=False)
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.get_level_values(0)
            if not h.empty:
                out[name] = h
        except:
            continue
    return out



def _yahoo_options_session():
    try:
        from curl_cffi import requests as cffi_req
        return cffi_req.Session(impersonate="chrome120")
    except ImportError:
        return None

@st.cache_data(ttl=900)
def fetch_options_chains(ticker: str = "SPY", n_exp: int = 4) -> tuple:
    """
    Descarga opciones y devuelve precios RAW (bid, ask, lastPrice).
    IV se calcula después con BS dado que yfinance's IV es poco fiable.
    Estrategia: curl_cffi → Yahoo v8 API directo → fallback yfinance.
    """
    log = logging.getLogger("vix_controller")

    def _clean(df_raw, spot_px):
        df_c = df_raw.copy()
        for col in ["bid","ask","lastPrice","openInterest","volume","strike"]:
            df_c[col] = pd.to_numeric(df_c.get(col, 0), errors="coerce").fillna(0)
        df_c = df_c[df_c["openInterest"] > 0]
        df_c = df_c[df_c["strike"] > 0]
        # midPrice: (bid+ask)/2 si ambos disponibles, else lastPrice
        df_c["midPrice"] = np.where(
            (df_c["bid"] > 0) & (df_c["ask"] > 0),
            0.5*(df_c["bid"] + df_c["ask"]),
            df_c["lastPrice"]
        )
        df_c = df_c[df_c["midPrice"] > 0]
        df_c = df_c.dropna(subset=["strike","midPrice"])
        df_c["moneyness"] = df_c["strike"] / spot_px
        return df_c.sort_values("strike").reset_index(drop=True)

    sess = _yahoo_options_session()
    if sess is not None:
        try:
            log.info(f"Options {ticker}: curl_cffi Chrome impersonation")
            base = f"https://query1.finance.yahoo.com/v8/finance/options/{ticker}"
            hdrs = {"Accept":"application/json","Referer":"https://finance.yahoo.com/",
                    "Accept-Language":"en-US,en;q=0.9"}
            r0   = sess.get(base, headers=hdrs, timeout=15)
            r0.raise_for_status()
            root = r0.json()["optionChain"]["result"][0]
            spot = float(root["quote"].get("regularMarketPrice", 0))
            if not spot: raise ValueError("spot=0")
            timestamps = root.get("expirationDates", [])
            today  = date.today()
            chains = {}
            sel = sorted(
                [(ts, datetime.fromtimestamp(ts).date().strftime("%Y-%m-%d"),
                  (datetime.fromtimestamp(ts).date() - today).days)
                 for ts in timestamps
                 if (datetime.fromtimestamp(ts).date() - today).days >= 7],
                key=lambda x: x[2])[:n_exp]
            for ts, exp_str, dte in sel:
                time.sleep(0.6)
                try:
                    rx = sess.get(f"{base}?date={ts}", headers=hdrs, timeout=15)
                    rx.raise_for_status()
                    opts = rx.json()["optionChain"]["result"][0]["options"][0]
                    c_df = _clean(pd.DataFrame(opts.get("calls",[])), spot)
                    p_df = _clean(pd.DataFrame(opts.get("puts", [])), spot)
                    if len(c_df) < 3 or len(p_df) < 3: continue
                    chains[exp_str] = {"calls":c_df,"puts":p_df,"dte":dte}
                except Exception as ex:
                    log.warning(f"curl_cffi chain {ticker} {exp_str}: {ex}")
            if chains:
                log.info(f"curl_cffi OK {ticker}: {len(chains)} chains · spot={spot:.2f}")
                return chains, spot
            log.warning(f"curl_cffi: no chains for {ticker} — fallback yfinance")
        except Exception as e:
            log.warning(f"curl_cffi failed {ticker}: {e} — fallback yfinance")

    # ── Fallback: yfinance con backoff ─────────────────────────────────────
    log.info(f"Options {ticker}: yfinance fallback")
    try:
        t = yf.Ticker(ticker)
        def _bo(fn, label, n=4):
            for i in range(n):
                try: return fn()
                except Exception as ex:
                    if any(k in str(ex).lower() for k in
                           ["rate limit","too many","429","throttle"]) and i < n-1:
                        w = 2**(i+1); log.warning(f"{label} RL→{w}s"); time.sleep(w)
                    else: raise
            return None
        exps = _bo(lambda: t.options, f"{ticker}.options")
        if not exps: return {}, None
        time.sleep(0.8)
        hist = _bo(lambda: t.history(period="2d"), f"{ticker}.hist")
        spot = float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else None
        if not spot: return {}, None
        today  = date.today()
        valid  = sorted(
            [(e,(datetime.strptime(e,"%Y-%m-%d").date()-today).days)
             for e in exps
             if (datetime.strptime(e,"%Y-%m-%d").date()-today).days >= 7],
            key=lambda x: x[1])[:n_exp]
        time.sleep(1.0)
        chains = {}; streak = 0
        for exp_str, dte in valid:
            if streak >= 2: time.sleep(12); streak = 0
            try:
                ch = _bo(lambda e=exp_str: t.option_chain(e), f"{ticker}.chain.{exp_str}")
                if ch is None: continue
                streak = 0
                chains[exp_str] = {
                    "calls": _clean(ch.calls, spot),
                    "puts":  _clean(ch.puts,  spot),
                    "dte":   dte,
                }
                time.sleep(1.5)
            except Exception as ex:
                if any(k in str(ex).lower() for k in ["rate limit","too many","429"]):
                    streak += 1
                else:
                    log.warning(f"yfinance chain {ticker} {exp_str}: {ex}")
        log.info(f"yfinance {ticker}: {len(chains)} chains · spot={spot:.2f}")
        return chains, spot
    except Exception as e:
        log.error(f"fetch_options_chains {ticker}: {e}")
        return {}, None


@st.cache_data(ttl=3600 * 6)
def fetch_cot_vix(n_weeks: int = 104) -> pd.DataFrame:
    """
    Descarga COT directo de la API Socrata del CFTC.
    Dataset: Disaggregated Futures — 72hh-3qpy
    Filtro: cftc_market_code = '1170E1' (VIX)
    """
    log = logging.getLogger("vix_controller")
    import urllib.request, json

    # Socrata API — Disaggregated Futures
    api_id = "72hh-3qpy"
    limit = min(n_weeks + 20, 2000)
    url = (f"https://publicreporting.cftc.gov/resource/{api_id}.json"
           f"?$where=cftc_market_code='1170E1'"
           f"&$order=report_date_as_yyyy_mm_dd DESC"
           f"&$limit={limit}")

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                    "User-Agent": "VIXController/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        if not data:
            log.error("COT API: respuesta vacía")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        log.info(f"COT API: {len(df)} filas descargadas")

        # Parsear fecha
        if "report_date_as_yyyy_mm_dd" in df.columns:
            df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce")
        elif "as_of_date_in_form_yymmdd" in df.columns:
            df["date"] = pd.to_datetime(df["as_of_date_in_form_yymmdd"], errors="coerce")

        # Mapear columnas Socrata → nuestro esquema
        socrata_map = {
            "open_interest_all":                       "oi",
            "lev_money_positions_long_all":             "mm_long",
            "lev_money_positions_short_all":            "mm_short",
            "lev_money_positions_spread_all":           "mm_spread",
            "asset_mgr_positions_long_all":             "asset_long",
            "asset_mgr_positions_short_all":            "asset_short",
            "dealer_positions_long_all":                "dealer_long",
            "dealer_positions_short_all":               "dealer_short",
            "other_rept_positions_long_all":            "other_long",
            "other_rept_positions_short_all":           "other_short",
        }
        df = df.rename(columns={k: v for k, v in socrata_map.items() if k in df.columns})

        # Convertir a numérico
        num_cols = ["oi", "mm_long", "mm_short", "mm_spread", "asset_long",
                    "asset_short", "dealer_long", "dealer_short", "other_long", "other_short"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # Métricas derivadas
        if "mm_long" in df.columns and "mm_short" in df.columns:
            df["net_mm"] = df["mm_long"] - df["mm_short"]
            df["net_mm_pct"] = (df["net_mm"] / df["oi"] * 100).where(df["oi"] > 0)
            df["net_mm_pct_pctile"] = df["net_mm_pct"].rank(pct=True) * 100

        if "dealer_long" in df.columns and "dealer_short" in df.columns:
            df["net_dealer"] = df["dealer_long"] - df["dealer_short"]

        if "asset_long" in df.columns and "asset_short" in df.columns:
            df["net_commercial"] = df["asset_long"] - df["asset_short"]

        df = df.sort_values("date").reset_index(drop=True)
        last_ok = df["date"].dropna().iloc[-1].strftime("%Y-%m-%d") if not df["date"].dropna().empty else "?"
        log.info(f"COT VIX: {len(df)} semanas · última: {last_ok}")
        return df.tail(n_weeks).reset_index(drop=True)

    except Exception as e:
        log.error(f"fetch_cot_vix: {e}")
        return pd.DataFrame()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COT — Commitments of Traders (CFTC Public API)
# Futuros VIX: código CFTC 1170E1 · Disaggregated Report
# API: https://publicreporting.cftc.gov (Socrata, sin auth)
# Publicación: martes ~15:30 ET con datos del martes anterior
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COT_VIX_CODE   = "1170E1"                        # CBOE VIX VOLATILITY INDEX
COT_API_BASE   = "https://publicreporting.cftc.gov/resource"
COT_DISAGG_ID  = "72hh-3qpy"                     # Disaggregated Futures & Options Combined
COT_LEGACY_ID  = "6dca-aqww"                     # Legacy (si disagg falla)

@st.cache_data(ttl=3600)
def load_master_parquet() -> pd.DataFrame:
    """
    Lee el histórico desde data/master.parquet (repo de GitHub).
    Instantáneo — sin red, sin Drive, sin gdown.
    El notebook exporta: df.to_parquet('data/master.parquet') y hace push.
    Columnas clave: VXX_Close, M1_Price, In_Contango, Contango_pct, VIX_Close
    """
    log = logging.getLogger("vix_controller")
    try:
        df = pd.read_parquet(PARQUET_PATH)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        log.info(f"Parquet: {len(df):,} filas · {df.index[-1].strftime('%Y-%m-%d')}")
        return df
    except Exception as e:
        log.error(f"Error parquet: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=55)
def fetch_today_prices():
    """Precios del día: VXX, SVXY, SVIX, VIX, SPY."""
    out = {}
    for name, sym in [("VXX","VXX"),("SVXY","SVXY"),("SVIX","SVIX"),
                       ("VIX","^VIX"),("SPY","SPY")]:
        try:
            h = yf.Ticker(sym).history(period="5d")
            if not h.empty:
                out[name] = dict(
                    close=round(float(h['Close'].iloc[-1]), 2),
                    prev =round(float(h['Close'].iloc[-2]), 2) if len(h) > 1 else None,
                    date =h.index[-1].date(),
                )
        except:
            continue
    return out


