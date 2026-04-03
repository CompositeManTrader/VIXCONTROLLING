import plotly.graph_objects as go
import pandas as pd
import numpy as np
from scipy.interpolate import griddata
from core import now_cdmx, C, MN

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

# ─── Métricas de skew (usa columna 'iv' BS) ────────────────────────────────
def compute_skew_metrics(chains: dict, spot: float) -> dict:
    """
    Métricas de skew del primer vencimiento válido usando IV Black-Scholes.
    """
    metrics = {}
    if not chains or not spot: return metrics

    for exp_str, data in sorted(chains.items(), key=lambda x: x[1]["dte"]):
        puts  = data["puts"]
        calls = data["calls"]
        dte   = data["dte"]
        if "iv" not in puts.columns or "iv" not in calls.columns: continue
        if len(puts) < 5 or len(calls) < 5: continue

        def get_iv_at_m(df, target, tol=0.05):
            sub = df[df["moneyness"].between(target-tol, target+tol)]
            if sub.empty: return np.nan
            w = sub["openInterest"].values + 1
            return float(np.average(sub["iv"].values, weights=w))

        atm_iv   = get_iv_at_m(puts, 1.00, 0.03)
        if np.isnan(atm_iv): atm_iv = get_iv_at_m(calls, 1.00, 0.03)
        put_25d  = get_iv_at_m(puts,  0.90, 0.04)
        call_25d = get_iv_at_m(calls, 1.10, 0.04)

        rr25 = (call_25d - put_25d)*100 if not (np.isnan(put_25d) or np.isnan(call_25d)) else np.nan
        bf25 = ((call_25d+put_25d)/2 - atm_iv)*100 if not np.isnan(atm_iv) else np.nan

        sp = puts[puts["moneyness"].between(0.80, 1.00)]
        if len(sp) >= 3:
            coef = np.polyfit(sp["moneyness"].values, sp["iv"].values, 1)[0]
            skew_slope = coef * 0.10 * 100
        else:
            skew_slope = np.nan

        pc_ratio = (puts["volume"].sum() / calls["volume"].sum()
                    if calls["volume"].sum() > 0 else np.nan)

        metrics = {
            "exp": exp_str, "dte": dte,
            "atm_iv":     round(atm_iv*100, 2)  if not np.isnan(atm_iv)    else None,
            "put_25d_iv": round(put_25d*100, 2)  if not np.isnan(put_25d)   else None,
            "call_25d_iv":round(call_25d*100,2)  if not np.isnan(call_25d)  else None,
            "rr25":       round(rr25, 2)          if not np.isnan(rr25)      else None,
            "bf25":       round(bf25, 2)          if not np.isnan(bf25)      else None,
            "skew_slope": round(skew_slope, 2)    if not np.isnan(skew_slope)else None,
            "pc_ratio":   round(pc_ratio, 3)      if not np.isnan(pc_ratio)  else None,
        }
        break
    return metrics

# ─── Chart: Skew Curves ────────────────────────────────────────────────────
SKEW_PALETTE = [
    "#58A6FF","#F0883E","#3FB950","#BC8CFF",
    "#39D2C0","#D29922","#F85149","#79C0FF",
]

def build_skew_curves(chains: dict, spot: float,
                      moneyness_range=(0.75, 1.25),
                      y_mode: str = "moneyness") -> go.Figure:
    """
    Curvas IV (BS) vs Moneyness o log-moneyness por vencimiento.
    y_mode: 'moneyness' → % vs spot | 'log' → ln(K/F)
    Usa columna 'iv' (BS calculado), no yfinance.
    """
    fig = go.Figure()
    if not chains or not spot: return fig
    lo, hi = moneyness_range

    for idx, (exp_str, data) in enumerate(sorted(chains.items(), key=lambda x: x[1]["dte"])):
        clr   = SKEW_PALETTE[idx % len(SKEW_PALETTE)]
        dte   = data["dte"]; T = dte / 365.0
        puts  = data["puts"][data["puts"]["moneyness"].between(lo, 1.02)].copy()
        calls = data["calls"][data["calls"]["moneyness"].between(0.98, hi)].copy()
        combined = pd.concat([puts, calls]).drop_duplicates("strike").sort_values("moneyness")
        if len(combined) < 3: continue

        iv_smooth = combined["iv"].rolling(3, min_periods=1, center=True).mean()

        if y_mode == "log":
            F = spot * np.exp(0 * T)   # r, q are baked into iv already
            x_vals = np.log(combined["strike"].values / spot)  # approx log-moneyness
            x_label = "Log-moneyness  ln(K/S)"
            x_suffix = ""
        else:
            x_vals  = combined["moneyness"].values * 100 - 100
            x_label = "% vs Spot  (neg=OTM puts | pos=OTM calls)"
            x_suffix = "%"

        fig.add_trace(go.Scatter(
            x=x_vals, y=iv_smooth * 100,
            mode="lines+markers", name=f"{exp_str} ({dte}d)",
            line=dict(color=clr, width=2.5, shape="spline"),
            marker=dict(size=5, color=clr, opacity=0.7),
            hovertemplate=f"<b>{exp_str}</b><br>x: %{{x:.2f}}{x_suffix}<br>IV(BS): %{{y:.1f}}%<extra></extra>",
        ))

    fig.add_vline(x=0, line_dash="dash", line_color="#8B949E", line_width=1.5,
                  annotation_text="ATM", annotation_font=dict(size=10, color="#8B949E"))
    fig.update_layout(
        title=dict(text="<b>Volatility Skew</b><sup>  IV Black-Scholes por vencimiento</sup>",
                   font=dict(size=13, color="#C9D1D9", family="Inter"), x=0.5),
        template="plotly_dark", paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
        height=420, margin=dict(l=55, r=30, t=60, b=50),
        xaxis=dict(title=dict(text=x_label, font=dict(size=10, color="#8B949E")),
                   gridcolor="#21262D", zeroline=True, zerolinecolor="#30363D",
                   tickfont=dict(size=10, color="#8B949E", family="JetBrains Mono")),
        yaxis=dict(title=dict(text="Implied Volatility BS (%)", font=dict(size=10, color="#8B949E")),
                   gridcolor="#21262D",
                   tickfont=dict(size=10, color="#8B949E", family="JetBrains Mono"),
                   ticksuffix="%"),
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="right", x=0.99,
                    bgcolor="rgba(22,27,34,0.9)", bordercolor="#30363D", borderwidth=1,
                    font=dict(size=9, color="#C9D1D9", family="JetBrains Mono")),
        hovermode="x unified",
    )
    return fig


# ─── Chart: ATM Term Structure ─────────────────────────────────────────────
def build_atm_term_structure(chains: dict, spot: float) -> go.Figure:
    fig = go.Figure()
    if not chains or not spot: return fig
    rows = []
    for exp_str, data in sorted(chains.items(), key=lambda x: x[1]["dte"]):
        dte = data["dte"]
        atm = pd.concat([
            data["puts"][data["puts"]["moneyness"].between(0.97, 1.03)],
            data["calls"][data["calls"]["moneyness"].between(0.97, 1.03)],
        ])
        if atm.empty or "iv" not in atm.columns: continue
        atm_iv = float(np.average(atm["iv"].values,
                                  weights=atm["openInterest"].values + 1)) * 100
        rows.append({"dte":dte,"atm_iv":atm_iv,"exp":exp_str})
    if not rows: return fig
    df_atm = pd.DataFrame(rows).sort_values("dte")
    fig.add_trace(go.Scatter(
        x=df_atm["dte"], y=df_atm["atm_iv"],
        mode="lines+markers+text", name="ATM IV (BS)",
        line=dict(color="#39D2C0", width=3, shape="spline"),
        marker=dict(size=10, color="#39D2C0", line=dict(width=2, color="#0D1117")),
        text=[f"{v:.1f}%" for v in df_atm["atm_iv"]],
        textposition="top center",
        textfont=dict(size=9, color="#C9D1D9", family="JetBrains Mono"),
        hovertemplate="DTE: %{x}d<br>ATM IV: %{y:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="<b>ATM IV Term Structure</b><sup>  IV en el dinero por vencimiento</sup>",
                   font=dict(size=13, color="#C9D1D9", family="Inter"), x=0.5),
        template="plotly_dark", paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
        height=300, margin=dict(l=55, r=30, t=60, b=50),
        xaxis=dict(title=dict(text="Días al Vencimiento (DTE)", font=dict(size=10, color="#8B949E")),
                   gridcolor="#21262D",
                   tickfont=dict(size=10, color="#8B949E", family="JetBrains Mono")),
        yaxis=dict(title=dict(text="ATM IV (%)", font=dict(size=10, color="#8B949E")),
                   gridcolor="#21262D",
                   tickfont=dict(size=10, color="#8B949E", family="JetBrains Mono"),
                   ticksuffix="%"),
        hovermode="x unified", showlegend=False,
    )
    return fig


# ─── Chart: IV Surface 3D (griddata — método del otro proyecto) ────────────
def build_iv_surface(chains: dict, spot: float,
                     moneyness_range=(0.80, 1.20), n_grid=40,
                     y_mode="moneyness") -> go.Figure:
    """
    Superficie 3D con scipy.griddata (lineal + nearest fallback).
    X = DTE, Y = moneyness o log-moneyness, Z = IV% BS.
    Mismo método que Volatility Surface de Drosogiannis.
    """
    fig = go.Figure()
    if not chains or not spot: return fig
    lo, hi = moneyness_range

    all_X, all_Y, all_Z = [], [], []
    for exp_str, data in chains.items():
        dte = data["dte"]
        pts = pd.concat([
            data["puts"][data["puts"]["moneyness"].between(lo, 1.02)],
            data["calls"][data["calls"]["moneyness"].between(0.98, hi)],
        ]).drop_duplicates("strike")
        if len(pts) < 4 or "iv" not in pts.columns: continue
        if y_mode == "log":
            y_vals = np.log(pts["strike"].values / spot)
        else:
            y_vals = pts["moneyness"].values * 100 - 100   # % vs spot
        all_X.extend([dte] * len(pts))
        all_Y.extend(y_vals.tolist())
        all_Z.extend((pts["iv"].values * 100).tolist())

    if len(all_X) < 8: return fig
    X = np.array(all_X); Y = np.array(all_Y); Z = np.array(all_Z)

    # Grid regular
    xi = np.linspace(X.min(), X.max(), n_grid)
    yi = np.linspace(Y.min(), Y.max(), n_grid)
    xi_g, yi_g = np.meshgrid(xi, yi)

    zi = griddata((X, Y), Z, (xi_g, yi_g), method="linear")
    zi2 = griddata((X, Y), Z, (xi_g, yi_g), method="nearest")
    zi  = np.where(np.isnan(zi), zi2, zi)   # fill NaN con nearest

    y_label = "Log-moneyness ln(K/S)" if y_mode == "log" else "% vs Spot"

    fig.add_trace(go.Surface(
        x=xi, y=yi, z=zi,
        colorscale="Viridis",
        colorbar=dict(title=dict(text="IV %", font=dict(color="#8B949E",size=10)),
                      tickfont=dict(color="#8B949E",size=9), len=0.6, thickness=12),
        hovertemplate="DTE: %{x:.0f}d<br>Y: %{y:.2f}<br>IV: %{z:.1f}%<extra></extra>",
        opacity=0.92,
    ))
    fig.update_layout(
        title=dict(text="<b>Implied Volatility Surface</b><sup>  IV Black-Scholes · griddata interpolation</sup>",
                   font=dict(size=14, color="#C9D1D9", family="Inter"), x=0.5),
        scene=dict(
            xaxis=dict(title="DTE (días)", gridcolor="#30363D", backgroundcolor="#0D1117",
                       tickfont=dict(size=9, color="#8B949E")),
            yaxis=dict(title=y_label, gridcolor="#30363D", backgroundcolor="#0D1117",
                       tickfont=dict(size=9, color="#8B949E")),
            zaxis=dict(title="IV (%)", gridcolor="#30363D", backgroundcolor="#0D1117",
                       tickfont=dict(size=9, color="#8B949E")),
            bgcolor="#0D1117",
            camera=dict(eye=dict(x=-1.6, y=-1.6, z=0.9), up=dict(x=0,y=0,z=1)),
        ),
        paper_bgcolor="#0D1117", height=520, margin=dict(l=0,r=0,t=50,b=0),
    )
    return fig


# ─── Chart: IV Heatmap 2D ──────────────────────────────────────────────────
def build_iv_heatmap(chains: dict, spot: float,
                     moneyness_range=(0.82, 1.18), n_bins=35) -> go.Figure:
    fig = go.Figure()
    if not chains or not spot: return fig
    lo, hi = moneyness_range
    mon_grid = np.linspace(lo, hi, n_bins)
    dte_vals, iv_rows = [], []

    for exp_str, data in sorted(chains.items(), key=lambda x: int(x[1]["dte"])):
        dte = int(data["dte"])
        pts = pd.concat([
            data["puts"][data["puts"]["moneyness"].between(lo, 1.02)],
            data["calls"][data["calls"]["moneyness"].between(0.98, hi)],
        ]).drop_duplicates("moneyness").sort_values("moneyness")
        if len(pts) < 3 or "iv" not in pts.columns: continue
        iv_vals = pd.to_numeric(pts["iv"], errors="coerce").values * 100
        mon_vals = pd.to_numeric(pts["moneyness"], errors="coerce").values
        mask = np.isfinite(iv_vals) & np.isfinite(mon_vals)
        if mask.sum() < 3: continue
        iv_interp = np.interp(mon_grid, mon_vals[mask], iv_vals[mask],
                              left=np.nan, right=np.nan)
        dte_vals.append(dte); iv_rows.append(iv_interp)

    if not iv_rows: return fig
    Z = np.array(iv_rows)
    labels_x = [f"{(m*100-100):+.0f}%" for m in mon_grid]
    labels_y = [f"{d}d" for d in dte_vals]

    atm_idx = int(np.argmin(np.abs(mon_grid - 1.0)))
    fig.add_trace(go.Heatmap(
        z=Z, x=labels_x, y=labels_y,
        colorscale=[[0.0,"#1565C0"],[0.25,"#0288D1"],[0.50,"#3FB950"],
                    [0.70,"#D29922"],[0.85,"#F0883E"],[1.0,"#F85149"]],
        colorbar=dict(title=dict(text="IV %",font=dict(color="#8B949E",size=10)),
                      tickfont=dict(color="#8B949E",size=9), len=0.8, thickness=14),
        hoverongaps=False,
        hovertemplate="Δ Spot: %{x}<br>DTE: %{y}<br>IV(BS): %{z:.1f}%<extra></extra>",
        xgap=1, ygap=1,
    ))
    fig.add_vline(x=labels_x[atm_idx], line_dash="dash", line_color="#8B949E",
                  line_width=1.5,
                  annotation_text="ATM", annotation_font=dict(size=9, color="#8B949E"))
    fig.update_layout(
        title=dict(text="<b>IV Surface — Heatmap</b><sup>  Filas=DTE · Columnas=%Spot · Color=IV(BS)%</sup>",
                   font=dict(size=13, color="#C9D1D9", family="Inter"), x=0.5),
        template="plotly_dark", paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
        height=380, margin=dict(l=55, r=20, t=60, b=60),
        xaxis=dict(tickfont=dict(size=8,color="#8B949E",family="JetBrains Mono"),
                   title=dict(text="Distancia al Spot",font=dict(size=10,color="#8B949E")),
                   tickangle=-45),
        yaxis=dict(tickfont=dict(size=9,color="#8B949E",family="JetBrains Mono"),
                   title=dict(text="DTE",font=dict(size=10,color="#8B949E")),
                   autorange="reversed"),
    )
    return fig

def build_cot_positioning_chart(cot_df, window=104):
    """Net Managed Money positioning + percentile bands."""
    p = cot_df.tail(window).copy()
    if 'net_mm' not in p.columns or 'date' not in p.columns:
        return go.Figure()
    p = p.dropna(subset=['net_mm', 'date'])
    if len(p) < 5:
        return go.Figure()
    colors = ['#3FB950' if v >= 0 else '#F85149' for v in p['net_mm']]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=p['date'], y=p['net_mm'], marker_color=colors,
        name='Net MM', opacity=0.7))
    if 'net_mm_pct' in p.columns:
        fig.add_trace(go.Scatter(x=p['date'], y=p['net_mm'].rolling(8).mean(),
            name='SMA(8w)', line=dict(color='#39D2C0', width=2)))
    fig.add_hline(y=0, line_dash='dash', line_color='#8B949E', line_width=1)
    fig.update_layout(
        title=dict(text='<b>Managed Money Net Positioning</b><sup>  VIX Futures · CFTC COT</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=350, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Contratos (net)', gridcolor='#21262D',
                   tickfont=dict(size=9, color='#8B949E')),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig


def build_cot_oi_chart(cot_df, window=104):
    """Open Interest total."""
    p = cot_df.tail(window).copy()
    if 'oi' not in p.columns or 'date' not in p.columns:
        return go.Figure()
    p = p.dropna(subset=['oi', 'date'])
    if len(p) < 5:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p['date'], y=p['oi'], name='Open Interest',
        line=dict(color='#58A6FF', width=2), fill='tozeroy',
        fillcolor='rgba(88,166,255,0.1)'))
    fig.update_layout(
        title=dict(text='<b>Open Interest</b><sup>  VIX Futures</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=280, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Contratos', gridcolor='#21262D',
                   tickfont=dict(size=9, color='#8B949E')),
        hovermode='x unified', showlegend=False)
    return fig


def build_cot_breakdown_chart(cot_df, window=104):
    """Breakdown: MM, Dealers, Asset Managers."""
    p = cot_df.tail(window).copy()
    if 'date' not in p.columns:
        return go.Figure()
    p = p.dropna(subset=['date'])
    fig = go.Figure()
    traces = [
        ('net_mm', 'Managed Money', '#3FB950'),
        ('net_dealer', 'Dealers', '#F0883E'),
        ('net_commercial', 'Asset Managers', '#58A6FF'),
    ]
    for col, name, color in traces:
        if col in p.columns:
            fig.add_trace(go.Scatter(x=p['date'], y=p[col], name=name,
                line=dict(color=color, width=2)))
    fig.add_hline(y=0, line_dash='dash', line_color='#8B949E', line_width=1)
    fig.update_layout(
        title=dict(text='<b>Net Positioning by Category</b>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=280, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Contratos (net)', gridcolor='#21262D',
                   tickfont=dict(size=9, color='#8B949E')),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig

def compute_edge_analytics(df, edge_extra):
    out = {}
    bt = df[df['VIX_Close'].notna() & df['SPY_Close'].notna()].copy()
    if len(bt) < 60:
        return out

    log_ret = np.log(bt['SPY_Close'] / bt['SPY_Close'].shift(1))
    bt['RV5']  = log_ret.rolling(5).std()  * np.sqrt(252) * 100
    bt['RV10'] = log_ret.rolling(10).std() * np.sqrt(252) * 100
    bt['RV20'] = log_ret.rolling(20).std() * np.sqrt(252) * 100
    bt['RV60'] = log_ret.rolling(60).std() * np.sqrt(252) * 100
    bt['VRP']  = bt['VIX_Close'] - bt['RV20']

    vrp_2y = bt['VRP'].tail(504).dropna()
    if len(vrp_2y) > 20:
        out['vrp_percentile'] = round((vrp_2y < vrp_2y.iloc[-1]).mean() * 100, 0)

    if 'M1_Price' in bt.columns and 'M1_DTE' in bt.columns:
        m1 = bt['M1_Price']; dte = bt['M1_DTE']; spot = bt['VIX_Close']
        valid = (m1 > 0) & (dte > 0) & m1.notna() & dte.notna() & spot.notna()
        bt['Roll_Yield'] = np.where(valid, (m1 - spot) / m1 * (365 / dte) * 100, np.nan)

    if 'VVIX_Close' in bt.columns:
        bt['VVIX_VIX'] = np.where(bt['VIX_Close'] > 0, bt['VVIX_Close'] / bt['VIX_Close'], np.nan)

    if 'SKEW' in edge_extra and not edge_extra['SKEW'].empty:
        skew_df = edge_extra['SKEW'][['Close']].rename(columns={'Close': 'SKEW'})
        bt = bt.join(skew_df, how='left')

    if 'HYG' in edge_extra and 'IEF' in edge_extra:
        hyg = edge_extra['HYG'][['Close']].rename(columns={'Close': 'HYG'})
        ief = edge_extra['IEF'][['Close']].rename(columns={'Close': 'IEF'})
        bt = bt.join(hyg, how='left').join(ief, how='left')
        if 'HYG' in bt.columns and 'IEF' in bt.columns:
            bt['Credit_Spread'] = -(bt['HYG'].pct_change().rolling(20).sum() -
                                    bt['IEF'].pct_change().rolling(20).sum()) * 100

    # Calendario de eventos 2026
    today = pd.Timestamp(now_cdmx().date())
    upcoming = []
    events = {
        'FOMC': ['2026-01-28','2026-03-18','2026-05-06','2026-06-17',
                  '2026-07-29','2026-09-16','2026-10-28','2026-12-16'],
        'CPI':  ['2026-01-14','2026-02-12','2026-03-11','2026-04-14','2026-05-13',
                  '2026-06-10','2026-07-15','2026-08-12','2026-09-10','2026-10-13',
                  '2026-11-12','2026-12-10'],
        'NFP':  ['2026-01-09','2026-02-06','2026-03-06','2026-04-03','2026-05-08',
                  '2026-06-05','2026-07-02','2026-08-07','2026-09-04','2026-10-02',
                  '2026-11-06','2026-12-04'],
    }
    for ev_name, dates in events.items():
        for d in dates:
            dt = pd.Timestamp(d)
            diff = (dt - today).days
            if 0 <= diff <= 14:
                upcoming.append((ev_name, dt, diff))
    upcoming.sort(key=lambda x: x[2])
    out['upcoming_events'] = upcoming
    out['bt'] = bt
    return out


def build_vrp_chart(bt, window=252):
    p = bt.tail(window).dropna(subset=['VRP'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.index, y=p['VIX_Close'], name='VIX (Implied)',
        line=dict(color='#F85149', width=2)))
    fig.add_trace(go.Scatter(x=p.index, y=p['RV20'], name='RV20 (Realized)',
        line=dict(color='#58A6FF', width=2)))
    fig.add_trace(go.Scatter(x=p.index, y=p['VRP'], name='VRP (IV - RV)',
        fill='tozeroy', line=dict(color='#3FB950', width=1),
        fillcolor='rgba(63,185,80,0.15)'))
    fig.add_hline(y=0, line_dash='dash', line_color='#8B949E', line_width=1)
    fig.update_layout(
        title=dict(text='<b>Volatility Risk Premium</b><sup>  VIX - RV20 · Tu edge en puntos</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=350, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Vol Points', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig


def build_rv_chart(bt, window=252):
    p = bt.tail(window).dropna(subset=['RV20'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.index, y=p['VIX_Close'], name='VIX',
        line=dict(color='#F85149', width=2.5)))
    for col, lbl, clr in [('RV5','RV5 (1w)','#D29922'), ('RV10','RV10 (2w)','#F0883E'),
                           ('RV20','RV20 (1m)','#58A6FF'), ('RV60','RV60 (3m)','#BC8CFF')]:
        if col in p.columns:
            fig.add_trace(go.Scatter(x=p.index, y=p[col], name=lbl, line=dict(color=clr, width=1.2)))
    fig.update_layout(
        title=dict(text='<b>Implied vs Realized Vol</b><sup>  VIX encima = VRP positivo</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=350, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Vol %', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig


def build_roll_yield_chart(bt, window=252):
    if 'Roll_Yield' not in bt.columns:
        return go.Figure()
    p = bt.tail(window).dropna(subset=['Roll_Yield'])
    colors = ['#3FB950' if v > 0 else '#F85149' for v in p['Roll_Yield']]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=p.index, y=p['Roll_Yield'], marker_color=colors,
        name='Roll Yield %', opacity=0.7))
    fig.add_trace(go.Scatter(x=p.index, y=p['Roll_Yield'].rolling(20).mean(),
        name='SMA(20)', line=dict(color='#39D2C0', width=2)))
    fig.add_hline(y=0, line_dash='dash', line_color='#8B949E', line_width=1)
    fig.update_layout(
        title=dict(text='<b>Roll Yield</b><sup>  Carry anualizado · Verde=cobras</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=300, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Ann. %', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig


def build_vvix_ratio_chart(bt, window=252):
    if 'VVIX_VIX' not in bt.columns:
        return go.Figure()
    p = bt.tail(window).dropna(subset=['VVIX_VIX'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.index, y=p['VVIX_VIX'], name='VVIX/VIX',
        line=dict(color='#BC8CFF', width=2)))
    fig.add_hline(y=6, line_dash='dash', line_color='#F85149', line_width=1.5,
        annotation_text='  Danger > 6', annotation_font=dict(color='#F85149', size=10))
    fig.add_hline(y=5, line_dash='dot', line_color='#D29922', line_width=1,
        annotation_text='  Warning > 5', annotation_font=dict(color='#D29922', size=9))
    fig.update_layout(
        title=dict(text='<b>VVIX / VIX Ratio</b><sup>  > 6 = dealers anticipan spike</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=300, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Ratio', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        hovermode='x unified')
    return fig


def build_skew_chart(bt, window=252):
    if 'SKEW' not in bt.columns:
        return go.Figure()
    p = bt.tail(window).dropna(subset=['SKEW'])
    if len(p) < 10:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.index, y=p['SKEW'], name='CBOE SKEW',
        line=dict(color='#F0883E', width=2)))
    fig.add_hline(y=p['SKEW'].mean(), line_dash='dot', line_color='#8B949E', line_width=1,
        annotation_text=f'  Media: {p["SKEW"].mean():.0f}',
        annotation_font=dict(color='#8B949E', size=9))
    fig.add_hline(y=150, line_dash='dash', line_color='#F85149', line_width=1,
        annotation_text='  Extremo > 150', annotation_font=dict(color='#F85149', size=9))
    fig.update_layout(
        title=dict(text='<b>CBOE SKEW</b><sup>  Demanda de proteccion · > 150 = extremo</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=280, margin=dict(l=50, r=30, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='SKEW', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        hovermode='x unified', showlegend=False)
    return fig


def build_credit_chart(bt, window=252):
    if 'Credit_Spread' not in bt.columns:
        return go.Figure()
    p = bt.tail(window).dropna(subset=['Credit_Spread'])
    if len(p) < 10:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.index, y=p['Credit_Spread'], name='Credit Spread (HYG-IEF)',
        line=dict(color='#D29922', width=2)))
    fig.add_trace(go.Scatter(x=p.index, y=p['VIX_Close'], name='VIX', yaxis='y2',
        line=dict(color='#F85149', width=1.5, dash='dot')))
    fig.update_layout(
        title=dict(text='<b>Credit Spread vs VIX</b><sup>  Divergencia = warning</sup>',
                   font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=280, margin=dict(l=50, r=60, t=55, b=40),
        xaxis=dict(gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title='Credit Spread', gridcolor='#21262D', tickfont=dict(size=9, color='#8B949E')),
        yaxis2=dict(title='VIX', overlaying='y', side='right',
                    tickfont=dict(size=9, color='#F85149'), showgrid=False),
        legend=dict(orientation='h', y=1.02, bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified')
    return fig


def build_vxx_operational_chart(bt: pd.DataFrame,
                                 vxx_today: float,
                                 final_sig_today: int,
                                 ct_today: float | None) -> go.Figure:
    """
    Gráfica operativa VXX con dos subpaneles:

    Panel 1 — VXX + SMA(20) + BB 2σ:
      · Zona verde      : LONG activo (sig_final==1)
      · Zona roja tenue : Backwardation (sig_bb==1 pero ct==0)
      · ▲ verde         : Entrada (sig_final 0→1)
      · ▼ naranja       : Salida por BB (VXX cruzó BB_Upper)
      · ▼ rojo          : Salida por Contango Rule (CT se apagó)
      · 💎 hoy          : precio actual (verde=LONG, rojo=CASH)

    Panel 2 — Contango % histórico (barras verdes/rojas del CSV)
              + punto de hoy en CBOE live
    """
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.68, 0.32],
        vertical_spacing=0.03,
    )

    sig    = bt['sig_final']
    sig_bb = bt['sig_bb']
    ct     = bt['ct_filter']
    vxx    = bt['VXX_Close']
    y_top  = vxx.max() * 1.25

    # ── Zona LONG (verde) ─────────────────────────────────────
    long_y = np.where(sig == 1, y_top, np.nan)
    fig.add_trace(go.Scatter(
        x=bt.index, y=long_y, mode='none',
        fill='tozeroy', fillcolor='rgba(63,185,80,0.09)',
        showlegend=True, name='LONG activo', hoverinfo='skip',
    ), row=1, col=1)

    # ── Zona Backwardation (rojo tenue) ───────────────────────
    bkwd_y = np.where((sig_bb == 1) & (ct == 0), y_top, np.nan)
    fig.add_trace(go.Scatter(
        x=bt.index, y=bkwd_y, mode='none',
        fill='tozeroy', fillcolor='rgba(248,81,73,0.07)',
        showlegend=True, name='Backwardation', hoverinfo='skip',
    ), row=1, col=1)

    # ── BB + SMA + VXX ────────────────────────────────────────
    fig.add_trace(go.Scatter(x=bt.index, y=bt['BB_Upper'],
        mode='lines', name='BB 2σ',
        line=dict(color='#F85149', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=bt.index, y=bt['BB_Lower'],
        mode='lines', showlegend=False,
        line=dict(color='#F85149', width=0.5, dash='dot'),
        fill='tonexty', fillcolor='rgba(248,81,73,0.03)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=bt.index, y=bt['BB_SMA20'],
        mode='lines', name='SMA(20)',
        line=dict(color='#58A6FF', width=1.5, dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=bt.index, y=vxx,
        mode='lines', name='VXX',
        line=dict(color='#F0F6FC', width=2),
        hovertemplate='%{x|%Y-%m-%d}  VXX: $%{y:.2f}<extra></extra>'), row=1, col=1)

    # ── Flechas ───────────────────────────────────────────────
    for i in range(1, len(sig)):
        date     = sig.index[i]
        y_val    = vxx.iloc[i]
        prev_sig = sig.iloc[i-1];   cur_sig  = sig.iloc[i]
        prev_bb  = sig_bb.iloc[i-1]; cur_bb  = sig_bb.iloc[i]
        prev_ct  = ct.iloc[i-1];    cur_ct   = ct.iloc[i]

        if cur_sig == 1 and prev_sig == 0:
            # Entrada
            fig.add_annotation(x=date, y=y_val, yshift=-22,
                text="▲", showarrow=False,
                font=dict(size=16, color='#3FB950', family='JetBrains Mono'),
                row=1, col=1)
        elif cur_sig == 0 and prev_sig == 1:
            if cur_bb == 0 and prev_bb == 1:
                # Salida por BB (naranja)
                fig.add_annotation(x=date, y=y_val, yshift=22,
                    text="▼", showarrow=False,
                    font=dict(size=16, color='#D29922', family='JetBrains Mono'),
                    row=1, col=1)
            elif cur_ct == 0 and prev_ct == 1:
                # Salida por Contango Rule (rojo)
                fig.add_annotation(x=date, y=y_val, yshift=22,
                    text="▼", showarrow=False,
                    font=dict(size=16, color='#F85149', family='JetBrains Mono'),
                    row=1, col=1)
            else:
                # Ambas (naranja — BB dominó)
                fig.add_annotation(x=date, y=y_val, yshift=22,
                    text="▼", showarrow=False,
                    font=dict(size=16, color='#D29922', family='JetBrains Mono'),
                    row=1, col=1)

    # Punto de hoy
    today_clr = '#3FB950' if final_sig_today else '#F85149'
    fig.add_trace(go.Scatter(
        x=[bt.index[-1]], y=[vxx_today],
        mode='markers', name='HOY — LONG' if final_sig_today else 'HOY — CASH',
        marker=dict(size=14, color=today_clr,
                    line=dict(width=2, color='white'), symbol='diamond'),
        hovertemplate=f'HOY: ${vxx_today:.2f}<extra></extra>',
    ), row=1, col=1)

    # ── Panel 2: Contango histórico ───────────────────────────
    if 'Contango_pct' in bt.columns:
        ct_hist  = bt['Contango_pct'].fillna(0)
        bar_clrs = ['#3FB950' if v > 0 else '#F85149' for v in ct_hist]
        fig.add_trace(go.Bar(
            x=bt.index, y=ct_hist,
            name='Contango %', marker_color=bar_clrs, opacity=0.7,
            hovertemplate='%{x|%Y-%m-%d}  CT: %{y:+.2f}%<extra></extra>',
        ), row=2, col=1)
        if ct_today is not None:
            ct_clr = '#3FB950' if ct_today > 0 else '#F85149'
            fig.add_trace(go.Scatter(
                x=[bt.index[-1]], y=[ct_today],
                mode='markers', name=f'CT hoy: {ct_today:+.2f}%',
                marker=dict(size=10, color=ct_clr, symbol='diamond',
                            line=dict(width=2, color='white')),
            ), row=2, col=1)
        fig.add_hline(y=0, line_color='#484F58', line_width=1, row=2, col=1)

    # ── Layout ────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text="<b>VXX — Monitor Operativo BB(20, 2σ) + Contango Rule</b>"
                 "<sup>  ▲=Entrada  ▼🟡=Salida BB  ▼🔴=Salida CT  💎=Hoy</sup>",
            font=dict(size=13, color='#C9D1D9', family='Inter'), x=0.5,
        ),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=560, margin=dict(l=55, r=30, t=65, b=40),
        xaxis=dict(
            gridcolor='#21262D',
            tickfont=dict(size=10, color='#8B949E', family='JetBrains Mono'),
            rangeselector=dict(
                buttons=[
                    dict(count=1,  label="1M",  step="month", stepmode="backward"),
                    dict(count=3,  label="3M",  step="month", stepmode="backward"),
                    dict(count=6,  label="6M",  step="month", stepmode="backward"),
                    dict(count=1,  label="1A",  step="year",  stepmode="backward"),
                    dict(count=3,  label="3A",  step="year",  stepmode="backward"),
                    dict(step="all", label="Todo"),
                ],
                bgcolor='#161B22', activecolor='#F7931A',
                font=dict(size=9, color='#C9D1D9', family='JetBrains Mono'),
            ),
        ),
        xaxis2=dict(gridcolor='#21262D',
                    tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        yaxis=dict(title=dict(text="VXX ($)", font=dict(size=11, color='#8B949E')),
                   gridcolor='#21262D',
                   tickfont=dict(size=10, color='#8B949E', family='JetBrains Mono')),
        yaxis2=dict(title=dict(text="Contango %", font=dict(size=10, color='#8B949E')),
                    gridcolor='#21262D',
                    tickfont=dict(size=9, color='#8B949E', family='JetBrains Mono'),
                    zeroline=True, zerolinecolor='#30363D'),
        legend=dict(orientation='h', yanchor='bottom', y=1.05,
                    bgcolor='rgba(0,0,0,0)',
                    font=dict(size=9, color='#8B949E', family='JetBrains Mono')),
        hovermode='x unified', dragmode=False, bargap=0,
    )
    return fig



def build_term_chart(vix_spot, df_vx, show_prev=True):
    """VIXCentral-faithful term structure chart using scraped CBOE data."""
    fig = go.Figure()
    if df_vx.empty:
        return fig

    # Month labels from expiration
    labels = []
    for _, r in df_vx.iterrows():
        exp = r.get('Expiration')
        if pd.notna(exp):
            labels.append(MN.get(exp.month, str(exp.month)[:3]))
        else:
            labels.append(str(r.get('Symbol','')))

    xpos = list(range(len(df_vx)))
    prices = df_vx['Price'].tolist()

    # Previous close = Price - Change
    prev_prices = []
    for _, r in df_vx.iterrows():
        p = r['Price']
        c = r.get('Change', 0)
        if pd.notna(p) and p > 0 and pd.notna(c):
            prev_prices.append(round(p - c, 4))
        else:
            prev_prices.append(None)

    # Today's curve
    vx = [x for x, y in zip(xpos, prices) if pd.notna(y) and y > 0]
    vy = [y for y in prices if pd.notna(y) and y > 0]

    if vy:
        fig.add_trace(go.Scatter(
            x=vx, y=vy, mode='lines+markers+text',
            name='Last', line=dict(color='#4A90D9', width=3, shape='spline'),
            marker=dict(size=9, color='#4A90D9', line=dict(width=2, color='#0D1117')),
            text=[f"{v:.3f}" for v in vy],
            textposition='top center',
            textfont=dict(size=10, color='#C9D1D9', family='JetBrains Mono'),
            hovertemplate='%{text}<extra></extra>',
        ))

    # Previous day
    if show_prev:
        pvx = [x for x, y in zip(xpos, prev_prices) if y and y > 0]
        pvy = [y for y in prev_prices if y and y > 0]
        if len(pvy) >= 2:
            fig.add_trace(go.Scatter(
                x=pvx, y=pvy, mode='lines+markers',
                name='Previous Close',
                line=dict(color='#8B949E', width=1.5, dash='dot', shape='spline'),
                marker=dict(size=5, color='#8B949E', symbol='diamond'),
                hovertemplate='Prev: %{y:.3f}<extra></extra>',
            ))

    # VIX Index dashed line
    if vix_spot:
        fig.add_hline(y=vix_spot['price'], line_dash="dash", line_color="#3FB950", line_width=2,
                      annotation_text=f"  {vix_spot['price']:.2f}",
                      annotation_position="right",
                      annotation_font=dict(size=12, color="#3FB950", family="Inter"))
        fig.add_trace(go.Scatter(x=[None], y=[None], mode='lines', name='VIX Index',
                                 line=dict(color='#3FB950', width=2, dash='dash'), showlegend=True))

    all_y = vy + ([vix_spot['price']] if vix_spot else [])
    y_min = min(all_y) - 1.5 if all_y else 15
    y_max = max(all_y) + 1.5 if all_y else 30

    fig.update_layout(
        title=dict(
            text="<b>VIX Futures Term Structure</b><br><sup>Source: CBOE Delayed Quotes · vixcontroller</sup>",
            font=dict(size=15, color='#C9D1D9', family='Inter'), x=0.5),
        template='plotly_dark', paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
        height=420, margin=dict(l=50, r=30, t=65, b=50),
        xaxis=dict(tickvals=xpos, ticktext=labels,
                   tickfont=dict(size=11, color='#8B949E', family='JetBrains Mono'),
                   gridcolor='#21262D', showline=True, linecolor='#30363D',
                   title=dict(text="Future Month", font=dict(size=11, color='#8B949E', family='Inter'))),
        yaxis=dict(range=[y_min, y_max],
                   title=dict(text="Volatility", font=dict(size=11, color='#8B949E', family='Inter')),
                   tickfont=dict(size=11, color='#8B949E', family='JetBrains Mono'),
                   gridcolor='#21262D', showline=True, linecolor='#30363D'),
        legend=dict(orientation='v', yanchor='top', y=0.99, xanchor='right', x=0.99,
                    bgcolor='rgba(22,27,34,0.9)', bordercolor='#30363D', borderwidth=1,
                    font=dict(size=10, color='#C9D1D9', family='JetBrains Mono')),
        hoverlabel=dict(bgcolor='#1C2128', bordercolor='#58A6FF',
                        font=dict(size=11, family='JetBrains Mono', color='#C9D1D9')),
        hovermode='x unified',
    )
    return fig





# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIN AUTO-REFRESH — solo botón manual en sidebar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEADER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
now_str = now_cdmx().strftime("%Y-%m-%d %H:%M:%S") + " CDMX"
_h = now_cdmx().hour + now_cdmx().minute / 60
mkt_status = "MARKET OPEN" if 8.5 <= _h < 15 and now_cdmx().weekday() < 5 else "MARKET CLOSED"
mkt_clr = "#3FB950" if "OPEN" in mkt_status else "#8B949E"
st.markdown(f"""
<div class="hdr">
    <div class="logo-box">
        <div class="logo-icon">Vc</div>
        <div>
            <div class="logo-text">VIX CONTROLLER</div>
            <div class="logo-tag">Volatility Intelligence Platform</div>
        </div>
    </div>
    <div class="sub">
        <span style="color:{mkt_clr};font-weight:600">{mkt_status}</span> · {now_str}<br>
        Source: CBOE Delayed Quotes · Actualiza con botón manual
    </div>
</div>
""", unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIDEBAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    N_MONTHS = st.slider("Max futures months", 4, 12, 8)
    SHOW_PREV = st.checkbox("Show previous day", True)
    SHOW_TABLE = st.checkbox("Show data table", True)
    st.markdown("---")
    st.markdown("**🔄 Actualizar datos**")
    if st.button("📡 Refresh CBOE + yfinance", key="btn_refresh_cboe"):
        scrape_cboe_futures.clear()
        fetch_vix_spot.clear()
        fetch_etps.clear()
        fetch_today_prices.clear()
        st.rerun()
    if st.button("🗄️ Recargar Parquet (repo)", key="btn_reload_parquet"):
        load_master_parquet.clear()
        build_strategy_cached.clear()
        st.rerun()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FETCH DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.spinner("🌐 Scraping CBOE delayed quotes…"):
    df_vx = scrape_cboe_futures()

# Mostrar diagnóstico en sidebar siempre
with st.sidebar:
    debug_msg = st.session_state.get("scrape_debug", "")
    if debug_msg:
        if debug_msg.startswith("❌"):
            st.error(debug_msg)
        else:
            st.info(f"🔍 {debug_msg}")
    html_sample = st.session_state.get("scrape_html_sample", "")
    if html_sample:
        st.warning("⚠️ No se encontró tabla VX — fragmento HTML:")
        st.code(html_sample[:600], language="html")

vix_spot = fetch_vix_spot()
etps = fetch_etps()

# Limit to N_MONTHS
if not df_vx.empty and len(df_vx) > N_MONTHS:
    df_vx = df_vx.head(N_MONTHS).reset_index(drop=True)

# Extract M1/M2 prices
m1p = df_vx['Price'].iloc[0] if not df_vx.empty and pd.notna(df_vx['Price'].iloc[0]) else None
m2p = df_vx['Price'].iloc[1] if len(df_vx) > 1 and pd.notna(df_vx['Price'].iloc[1]) else None
front_ct = cpct(m1p, m2p)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
