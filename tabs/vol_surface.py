import streamlit as st
import pandas as pd
import numpy as np
from core import now_cdmx
from core.data_fetchers import fetch_options_chains
from core.charts import (compute_bs_iv_for_chains, compute_skew_metrics,
                          build_skew_curves, build_atm_term_structure,
                          build_iv_surface, build_iv_heatmap)

def render():
    
        # ── Controles ─────────────────────────────────────────────
        col_c1, col_c2, col_c3, col_c4 = st.columns([1,1,1,1])
        with col_c1:
            skew_ticker = st.text_input(
                "Subyacente (ticker)", value="SPY",
                help="Cualquier ticker de opciones: SPY, QQQ, AAPL, TSLA, IWM, GLD, TLT…",
            ).strip().upper()
        with col_c2:
            n_exps = st.slider("Nº Vencimientos", 2, 12, 6,
                               help="Más vencimientos = superficie más completa pero más lento (~1s c/u)")
        with col_c3:
            skew_rfr = st.number_input("Risk-Free Rate (r)", 0.0, 0.15,
                                       value=0.043, step=0.001, format="%.3f",
                                       help="Tasa libre de riesgo anualizada (ej: 4.3%=0.043)")
        with col_c4:
            skew_div = st.number_input("Dividend Yield (q)", 0.0, 0.10,
                                       value=0.013, step=0.001, format="%.3f",
                                       help="Yield de dividendo continuo (SPY≈1.3%)")
    
        col_c5, col_c6, col_c7, col_c8 = st.columns([1,1,1,1])
        with col_c5:
            mon_lo = st.slider("Strike mín (%spot)", 70, 90, 80) / 100
        with col_c6:
            mon_hi = st.slider("Strike máx (%spot)", 110, 140, 125) / 100
        with col_c7:
            y_axis_mode = st.selectbox("Eje Y", ["% vs Spot", "Log-moneyness ln(K/S)"],
                                       help="Log-moneyness es la convención académica de BS")
            y_mode = "moneyness" if y_axis_mode.startswith("%") else "log"
        with col_c8:
            view_mode = st.selectbox("Vista superficie", ["🌐 3D Surface", "🗺️ Heatmap 2D"])
    
        if st.button("🔄 Actualizar opciones", key="refresh_options"):
            fetch_options_chains.clear()
            st.rerun()
    
        # ── Fetch raw data ────────────────────────────────────────
        est_secs = n_exps * 1.2 + 2
        with st.spinner(f"📡 Descargando {n_exps} vencimientos de {skew_ticker} (~{est_secs:.0f}s)…"):
            opt_chains_raw, opt_spot = fetch_options_chains(skew_ticker, n_exp=n_exps)
    
        if not opt_chains_raw or not opt_spot:
            st.error(f"❌ Yahoo Finance rate limit — no se cargaron opciones para **{skew_ticker}**.")
            st.info("💡 Espera 3-5 min · baja a 2 vencimientos · o intenta en horario de mercado (9:30-16:00 ET).")
            st.stop()
    
        # ── Calcular IV con Black-Scholes (Brent's method) ───────
        with st.spinner("⚙️ Calculando IV Black-Scholes…"):
            opt_chains = compute_bs_iv_for_chains(opt_chains_raw, opt_spot,
                                                  r=skew_rfr, q=skew_div)
    
        if not opt_chains:
            st.warning("⚠️ No se pudo calcular IV BS para ningún vencimiento. "
                       "Ajusta r/q o amplía el rango de strikes.")
            st.stop()
    
        spot_disp = f"${opt_spot:.2f}"
        n_valid   = len(opt_chains)
    
        # ── Métricas de skew ─────────────────────────────────────
        sk = compute_skew_metrics(opt_chains, opt_spot)
    
        def _fmt(v, sfx="", sign=False):
            return f"{'+' if sign and v>=0 else ''}{v:.2f}{sfx}" if v is not None else "—"
    
        rr_raw = sk.get("rr25"); pc_raw = sk.get("pc_ratio")
        rr_clr = "var(--r)" if (rr_raw and rr_raw < -3) else "var(--y)" if (rr_raw and rr_raw < 0) else "var(--g)"
        pc_clr = "var(--r)" if (pc_raw and pc_raw > 1.5) else "var(--y)" if (pc_raw and pc_raw > 1.0) else "var(--g)"
    
        st.markdown(f"""
        <div class="mrow">
            <div class="mpill"><div class="ml">{skew_ticker} Spot</div><div class="mv nt">{spot_disp}</div></div>
            <div class="mpill"><div class="ml">ATM IV BS · {sk.get('exp','—')} ({sk.get('dte','?')}d)</div>
                <div class="mv nt">{_fmt(sk.get('atm_iv'),'%')}</div></div>
            <div class="mpill"><div class="ml">25Δ Risk Reversal</div>
                <div class="mv" style="color:{rr_clr}">{_fmt(sk.get('rr25'),' pts',True)}</div></div>
            <div class="mpill"><div class="ml">25Δ Butterfly</div>
                <div class="mv nt">{_fmt(sk.get('bf25'),' pts',True)}</div></div>
            <div class="mpill"><div class="ml">Skew Slope /10%</div>
                <div class="mv nt">{_fmt(sk.get('skew_slope'),' pts')}</div></div>
            <div class="mpill"><div class="ml">P/C Vol Ratio</div>
                <div class="mv" style="color:{pc_clr}">{_fmt(sk.get('pc_ratio'))}</div></div>
            <div class="mpill"><div class="ml">Vencimientos BS</div>
                <div class="mv nt">{n_valid}</div></div>
            <div class="mpill"><div class="ml">r / q</div>
                <div class="mv nt">{skew_rfr:.1%} / {skew_div:.1%}</div></div>
        </div>
        """, unsafe_allow_html=True)
    
        interp_parts = []
        if rr_raw is not None:
            if rr_raw < -4: interp_parts.append("🔴 **Risk Reversal muy negativo** — put skew extremo, fear elevado")
            elif rr_raw < -2: interp_parts.append("🟡 **Risk Reversal negativo moderado** — demanda de cobertura activa")
            else: interp_parts.append("🟢 **Risk Reversal neutro** — apetito por riesgo presente")
        if pc_raw is not None:
            if pc_raw > 1.5: interp_parts.append("🔴 **P/C Ratio > 1.5** — flujo dominante en puts, hedging institucional")
            elif pc_raw > 1.0: interp_parts.append("🟡 **P/C Ratio > 1.0** — ligero sesgo defensivo")
            else: interp_parts.append("🟢 **P/C Ratio < 1.0** — flujo en calls, risk-on")
        if interp_parts:
            with st.expander("📊 Lectura del Skew", expanded=True):
                for l in interp_parts: st.markdown(l)
    
        st.markdown("<div style='border-top:1px solid #30363D;margin:0.5rem 0'></div>",
                    unsafe_allow_html=True)
    
        # ── Skew Curves + ATM Term Structure ─────────────────────
        col_sk, col_atm = st.columns([1.6, 1])
        with col_sk:
            try:
                fig_sk = build_skew_curves(opt_chains, opt_spot,
                                           moneyness_range=(mon_lo, mon_hi),
                                           y_mode=y_mode)
                if fig_sk.data:
                    st.plotly_chart(fig_sk, width="stretch",
                                    config=dict(displayModeBar=True,
                                                modeBarButtonsToRemove=["lasso2d","select2d"]))
                else: st.info("No hay suficientes datos para graficar el skew.")
            except Exception as e: st.error(f"Error skew: {e}")
    
        with col_atm:
            try:
                fig_atm = build_atm_term_structure(opt_chains, opt_spot)
                if fig_atm.data:
                    st.plotly_chart(fig_atm, width="stretch", config=dict(displayModeBar=False))
                else: st.info("No hay datos ATM.")
            except Exception as e: st.error(f"Error ATM TS: {e}")
    
        st.markdown("<div style='border-top:1px solid #30363D;margin:0.5rem 0'></div>",
                    unsafe_allow_html=True)
    
        # ── IV Surface ────────────────────────────────────────────
        if view_mode == "🌐 3D Surface":
            try:
                fig_surf = build_iv_surface(opt_chains, opt_spot,
                                            moneyness_range=(mon_lo, mon_hi),
                                            y_mode=y_mode)
                if fig_surf.data:
                    st.plotly_chart(fig_surf, width="stretch", config=dict(displayModeBar=True))
                else: st.info("No hay suficientes datos para la superficie 3D.")
            except Exception as e: st.error(f"Error IV Surface: {e}")
        else:
            try:
                fig_hm = build_iv_heatmap(opt_chains, opt_spot,
                                          moneyness_range=(mon_lo, mon_hi))
                if fig_hm.data:
                    st.plotly_chart(fig_hm, width="stretch", config=dict(displayModeBar=False))
                else: st.info("No hay suficientes datos para el heatmap.")
            except Exception as e: st.error(f"Error IV Heatmap: {e}")
    
        # ── Tabla por vencimiento ─────────────────────────────────
        with st.expander("📋 Tabla resumen por vencimiento"):
            rows_tbl = []
            for exp_str, data in sorted(opt_chains.items(), key=lambda x: x[1]["dte"]):
                dte_t = data["dte"]
                puts_t  = data["puts"];  calls_t = data["calls"]
                atm_all = pd.concat([
                    puts_t[puts_t["moneyness"].between(0.97,1.03)],
                    calls_t[calls_t["moneyness"].between(0.97,1.03)],
                ])
                atm_iv_t = (float(np.average(atm_all["iv"].values,
                                              weights=atm_all["openInterest"].values+1))*100
                            if not atm_all.empty and "iv" in atm_all.columns else np.nan)
                p90  = puts_t[puts_t["moneyness"].between(0.88,0.92)]["iv"].mean()
                c110 = calls_t[calls_t["moneyness"].between(1.08,1.12)]["iv"].mean()
                rr_t = (c110-p90)*100 if pd.notna(p90) and pd.notna(c110) else np.nan
                rows_tbl.append({
                    "Vencimiento": exp_str, "DTE": dte_t,
                    "ATM IV (BS)": f"{atm_iv_t:.1f}%" if not np.isnan(atm_iv_t) else "—",
                    "IV 90% put":  f"{p90*100:.1f}%"  if pd.notna(p90)  else "—",
                    "IV 110% call":f"{c110*100:.1f}%" if pd.notna(c110) else "—",
                    "RR ~25Δ":     f"{rr_t:+.1f} pts" if not np.isnan(rr_t) else "—",
                    "Puts": len(puts_t), "Calls": len(calls_t),
                })
            if rows_tbl:
                st.dataframe(pd.DataFrame(rows_tbl), width="stretch", hide_index=True)
    
        # ── High-IV Scanner: mejores strikes para vender primas ──
        with st.expander("🎯 Scanner: Strikes con Mayor IV (para venta de primas)", expanded=False):
            st.markdown("""<div style="font-family:'JetBrains Mono';font-size:0.72rem;color:#8B949E;margin-bottom:0.5rem">
            Opciones con IV más alta por vencimiento — candidatas para vender primas (put spreads, iron condors).
            Ordenadas por IV descendente. OI alto = más liquidez para ejecutar.
            </div>""", unsafe_allow_html=True)
    
            scanner_exp = st.selectbox("Vencimiento", sorted(opt_chains.keys(),
                key=lambda x: opt_chains[x]["dte"]),
                format_func=lambda x: f"{x} ({opt_chains[x]['dte']}d)",
                key="scanner_exp")
    
            if scanner_exp and scanner_exp in opt_chains:
                s_data = opt_chains[scanner_exp]
                s_dte = s_data["dte"]
    
                # Combinar puts y calls
                s_puts = s_data["puts"].copy()
                s_puts["type"] = "PUT"
                s_calls = s_data["calls"].copy()
                s_calls["type"] = "CALL"
                s_all = pd.concat([s_puts, s_calls], ignore_index=True)
    
                if "iv" in s_all.columns and len(s_all) > 0:
                    s_all["iv_pct"] = s_all["iv"] * 100
                    s_all["dist_spot"] = ((s_all["strike"] / opt_spot) - 1) * 100
                    s_all = s_all.sort_values("iv_pct", ascending=False)
    
                    # Top 20
                    top_iv = s_all.head(20)[["type", "strike", "iv_pct", "dist_spot",
                                              "midPrice", "bid", "ask", "openInterest", "volume"]].copy()
                    top_iv.columns = ["Tipo", "Strike", "IV (BS) %", "Dist Spot %",
                                      "Mid $", "Bid", "Ask", "OI", "Vol"]
                    for c in ["IV (BS) %", "Dist Spot %"]:
                        top_iv[c] = top_iv[c].round(2)
                    for c in ["Mid $", "Bid", "Ask"]:
                        top_iv[c] = top_iv[c].round(2)
                    top_iv["OI"] = top_iv["OI"].astype(int)
                    top_iv["Vol"] = top_iv["Vol"].astype(int)
    
                    st.dataframe(top_iv, width="stretch", hide_index=True)
    
                    # Resumen
                    avg_put_iv = s_puts["iv"].mean() * 100 if len(s_puts) > 0 else 0
                    avg_call_iv = s_calls["iv"].mean() * 100 if len(s_calls) > 0 else 0
                    max_iv_row = s_all.iloc[0]
                    st.markdown(f"""<div style="font-family:'JetBrains Mono';font-size:0.75rem;color:#C9D1D9;margin-top:0.4rem">
                        IV promedio puts: <b style="color:#F85149">{avg_put_iv:.1f}%</b> ·
                        IV promedio calls: <b style="color:#3FB950">{avg_call_iv:.1f}%</b> ·
                        Mayor IV: <b style="color:#D29922">{max_iv_row['type']} K={max_iv_row['strike']:.0f} → {max_iv_row['iv_pct']:.1f}%</b>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.info("No hay datos de IV para este vencimiento.")
    
        st.caption(
            f"IV calculada con Black-Scholes (Brent) · r={skew_rfr:.1%} · q={skew_div:.1%} · "
            f"Spot {skew_ticker}: {spot_disp} · {now_cdmx().strftime('%H:%M:%S')} CDMX"
        )
    
    
