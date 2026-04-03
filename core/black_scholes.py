def _bs_call(S, X, r, T, v, q):
    """Black-Scholes call price con dividendo continuo."""
    if S <= 0 or X <= 0 or T <= 0: return max(S - X, 0.0)
    if v <= 0: return max(S*np.exp(-q*T) - X*np.exp(-r*T), 0.0)
    d1 = (np.log(S/X) + (r - q + 0.5*v**2)*T) / (v*np.sqrt(T))
    d2 = d1 - v*np.sqrt(T)
    return S*np.exp(-q*T)*norm.cdf(d1) - X*np.exp(-r*T)*norm.cdf(d2)

def _bs_put(S, X, r, T, v, q):
    """Black-Scholes put price con dividendo continuo."""
    if S <= 0 or X <= 0 or T <= 0: return max(X - S, 0.0)
    if v <= 0: return max(X*np.exp(-r*T) - S*np.exp(-q*T), 0.0)
    d1 = (np.log(S/X) + (r - q + 0.5*v**2)*T) / (v*np.sqrt(T))
    d2 = d1 - v*np.sqrt(T)
    return X*np.exp(-r*T)*norm.cdf(-d2) - S*np.exp(-q*T)*norm.cdf(-d1)

def _bs_iv(S, X, r, T, price, option_type, q, tol=1e-6):
    """IV via Brent's method. Retorna NaN si no converge o fuera de bounds."""
    if T <= 0 or S <= 0 or X <= 0 or not np.isfinite(price) or price <= 0:
        return np.nan
    fn = _bs_call if option_type == "C" else _bs_put
    # Bounds de precio
    lo = max(S*np.exp(-q*T) - X*np.exp(-r*T), 0.0) if option_type == "C" \
         else max(X*np.exp(-r*T) - S*np.exp(-q*T), 0.0)
    hi = S*np.exp(-q*T) if option_type == "C" else X*np.exp(-r*T)
    if not (lo <= price <= hi):
        return np.nan
    try:
        iv = brentq(lambda v: price - fn(S, X, r, T, v, q), 1e-6, 5.0, xtol=tol)
        return np.nan if iv <= tol else iv
    except (ValueError, RuntimeError):
        return np.nan

# ─── Fetch raw options (sin IV de yfinance) ─────────────────────────────────

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


def compute_bs_iv_for_chains(chains: dict, spot: float, r: float, q: float) -> dict:
    """
    Aplica BS IV (Brent) a cada opción de cada chain.
    Agrega columna 'iv' (float, annualizado) y filtra NaN.
    r = risk-free rate anualizado
    q = dividend yield continuo
    """
    result = {}
    for exp_str, data in chains.items():
        dte = data["dte"]
        T   = dte / 365.0
        if T <= 0:
            continue
        for side, opt_type in [("calls","C"), ("puts","P")]:
            df = data[side].copy()
            df["iv"] = df.apply(
                lambda row: _bs_iv(spot, row["strike"], r, T,
                                   row["midPrice"], opt_type, q),
                axis=1
            )
            df = df[df["iv"].notna() & (df["iv"] > 0.005) & (df["iv"] < 5.0)]
            data[side] = df.reset_index(drop=True)
        if len(data["calls"]) >= 3 and len(data["puts"]) >= 3:
            result[exp_str] = data
    return result

