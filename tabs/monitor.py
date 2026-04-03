import streamlit as st
import pandas as pd
import numpy as np
from datetime import timedelta
from core import now_cdmx, cpct
from core.data_fetchers import load_master_parquet, fetch_today_prices
from core.strategy import build_strategy_cached
from core.charts import build_vxx_operational_chart

def render(m1p, m2p, df_vx, ct_source_override=None):
    
        # ── Cargar parquet (del repo, instantáneo) ────────────────
        df_master = load_master_parquet()
    
        if df_master.empty:
            st.error("❌ No se encontró data/master.parquet en el repositorio.")
            st.info("Ejecuta el notebook de actualización y haz push: df.to_parquet('data/master.parquet')")
            st.stop()
    
        # ── Aplicar estrategia (cacheado 1h) ──────────────────────
        bt = build_strategy_cached(df_master)
    
        # ── Precios de hoy (yfinance) ─────────────────────────────
        today_px   = fetch_today_prices()
        last_hist  = bt.iloc[-1]
        last_date  = bt.index[-1]
    
        vxx_today  = float(today_px.get('VXX',  {}).get('close', last_hist['VXX_Close']))
        svxy_today = float(today_px.get('SVXY', {}).get('close', 0))
        svix_today = float(today_px.get('SVIX', {}).get('close', 0))
        vix_val    = float(today_px.get('VIX',  {}).get('close', last_hist.get('VIX_Close', 0)))
    
        sma20  = float(last_hist['BB_SMA20'])
        bb_up  = float(last_hist['BB_Upper'])
    
        # BB signal de hoy (posición actual, sin shift)
        bb_pos = int(last_hist['sig_bb'])
        if bb_pos == 0 and vxx_today < sma20:   bb_sig_today = 1
        elif bb_pos == 1 and vxx_today > bb_up: bb_sig_today = 0
        else:                                    bb_sig_today = bb_pos
    
        # Contango live del CBOE (del Tab 1 — m1p, m2p en scope global)
        if m1p and m2p and m1p > 0:
            ct_today  = cpct(m1p, m2p)
            ct_source = "CBOE live"
            m1_sym    = df_vx['Symbol'].iloc[0] if not df_vx.empty else "M1"
            m2_sym    = df_vx['Symbol'].iloc[1] if len(df_vx) > 1 else "M2"
        else:
            ct_today  = float(last_hist.get('Contango_pct', 0)) if 'Contango_pct' in last_hist else None
            ct_source = "CSV histórico"
            m1_sym    = str(last_hist.get('M1_Symbol', 'M1'))
            m2_sym    = str(last_hist.get('M2_Symbol', 'M2'))
    
        in_ct_today     = ct_today is not None and ct_today > 0
        final_sig_today = int(bb_sig_today == 1 and in_ct_today)
    
        exec_date = now_cdmx().date() + timedelta(days=1)
        while exec_date.weekday() >= 5:
            exec_date += timedelta(days=1)
    
        pct_to_sma = (vxx_today / sma20 - 1) * 100 if sma20 else 0
        pct_to_bb  = (vxx_today / bb_up  - 1) * 100 if bb_up  else 0
        ct_str     = f"{ct_today:+.2f}%" if ct_today is not None else "N/A"
    
        if vix_val < 15:   regime, r_clr = "BAJO — óptimo",       "var(--g)"
        elif vix_val < 20: regime, r_clr = "NORMAL — bueno",      "var(--g)"
        elif vix_val < 28: regime, r_clr = "ELEVADO — precaución","var(--y)"
        else:              regime, r_clr = "CRISIS — peligro",    "var(--r)"
    
        def mcard(label, val, clr="nt"):
            return f'<div class="mpill"><div class="ml">{label}</div><div class="mv {clr}">{val}</div></div>'
    
        # ═══════════════════════════════════════════
        # SECCIÓN 1 — SEÑAL DE HOY
        # ═══════════════════════════════════════════
        sig_cls = "sig-long" if final_sig_today else "sig-cash"
        sig_txt = "LONG SVXY" if final_sig_today else "CASH"
        sig_clr = "var(--g)" if final_sig_today else "var(--r)"
        bb_ok   = "ok" if bb_sig_today else "no"
        ct_ok   = "ok" if in_ct_today  else "no"
    
        c1, c2, c3, c4 = st.columns([1.3, 1.5, 1.5, 1.3])
    
        with c1:
            st.markdown(f"""<div class="sig-box {sig_cls}">
                <div class="sl" style="color:{sig_clr}">{sig_txt}</div>
                <div class="sd">Ejecutar {exec_date.strftime('%Y-%m-%d')} al OPEN</div>
                <div class="sd">Señal cierre {last_date.strftime('%Y-%m-%d')}</div>
            </div>""", unsafe_allow_html=True)
    
        with c2:
            sma_clr = "var(--g)" if vxx_today < sma20 else "var(--r)"
            bb_clr  = "var(--g)" if vxx_today <= bb_up else "var(--r)"
            st.markdown(f"""<div class="icard">
                <div class="ic-title">📊 BB Timing — VXX</div>
                <div class="ic-row"><span class="ic-label">Señal BB</span>
                    <span class="ic-val"><span class="{bb_ok}">{"✓" if bb_sig_today else "✗"}</span>
                    {"&nbsp;LONG" if bb_sig_today else "&nbsp;CASH"}</span></div>
                <div class="ic-row"><span class="ic-label">VXX hoy</span>
                    <span class="ic-val" style="font-weight:700">${vxx_today:.2f}</span></div>
                <div class="ic-row"><span class="ic-label">SMA(20)</span>
                    <span class="ic-val" style="color:{sma_clr}">${sma20:.2f} ({pct_to_sma:+.1f}%)</span></div>
                <div class="ic-row"><span class="ic-label">BB 2σ</span>
                    <span class="ic-val" style="color:{bb_clr}">${bb_up:.2f} ({pct_to_bb:+.1f}%)</span></div>
            </div>""", unsafe_allow_html=True)
    
        with c3:
            ct_clr    = "var(--g)" if in_ct_today else "var(--r)"
            ct_estado = "CONTANGO" if in_ct_today else "BACKWARDATION"
            m1_disp   = f"${m1p:.2f}" if m1p else "—"
            m2_disp   = f"${m2p:.2f}" if m2p else "—"
            st.markdown(f"""<div class="icard">
                <div class="ic-title">📈 Contango ({ct_source})</div>
                <div class="ic-row"><span class="ic-label">Señal CT</span>
                    <span class="ic-val"><span class="{ct_ok}">{"✓" if in_ct_today else "✗"}</span>
                    <span style="color:{ct_clr};font-weight:700">&nbsp;{ct_estado}</span></span></div>
                <div class="ic-row"><span class="ic-label">{m1_sym} (M1)</span>
                    <span class="ic-val">{m1_disp}</span></div>
                <div class="ic-row"><span class="ic-label">{m2_sym} (M2)</span>
                    <span class="ic-val">{m2_disp}</span></div>
                <div class="ic-row"><span class="ic-label">Contango %</span>
                    <span class="ic-val" style="color:{ct_clr};font-weight:700">{ct_str}</span></div>
                <div class="ic-row"><span class="ic-label">VIX</span>
                    <span class="ic-val" style="color:{r_clr}">{vix_val:.1f} · {regime}</span></div>
            </div>""", unsafe_allow_html=True)
    
        with c4:
            svxy_chg = ""
            if today_px.get('SVXY', {}).get('prev'):
                d = svxy_today - today_px['SVXY']['prev']
                svxy_chg = f" ({d:+.2f})"
            st.markdown(f"""<div class="icard">
                <div class="ic-title">💼 Vehículos</div>
                <div class="ic-row"><span class="ic-label">SVXY (-0.5x)</span>
                    <span class="ic-val" style="color:var(--c);font-weight:700">${svxy_today:.2f}{svxy_chg}</span></div>
                <div class="ic-row"><span class="ic-label">SVIX (-1x)</span>
                    <span class="ic-val" style="color:var(--c)">${svix_today:.2f}</span></div>
                <div class="ic-row"><span class="ic-label">VIX Spot</span>
                    <span class="ic-val">{vix_val:.2f}</span></div>
                <div class="ic-row"><span class="ic-label">CSV al</span>
                    <span class="ic-val" style="color:var(--dim)">{last_date.strftime('%Y-%m-%d')}</span></div>
            </div>""", unsafe_allow_html=True)
    
        # Alertas
        if final_sig_today and pct_to_bb > -3:
            st.warning(f"⚠️ VXX a {abs(pct_to_bb):.1f}% de la BB Superior — posible salida pronto")
        if ct_today is not None and 0 < ct_today < 1:
            st.warning(f"⚠️ Contango muy bajo ({ct_today:.2f}%) — monitorear")
        if not final_sig_today and abs(pct_to_sma) < 2 and in_ct_today:
            st.info(f"🔔 Posible entrada pronto — VXX a {abs(pct_to_sma):.1f}% de SMA(20)")
        if not in_ct_today and bb_sig_today == 1:
            st.warning("⚠️ BB dice LONG pero hay backwardation — CASH por Contango Rule")
    
        st.markdown("<div style='border-top:1px solid #30363D;margin:0.8rem 0'></div>",
                    unsafe_allow_html=True)
    
        # ═══════════════════════════════════════════
        # SECCIÓN 2 — GRÁFICA VXX OPERATIVA
        # ═══════════════════════════════════════════
        fig_mon = build_vxx_operational_chart(
            bt=bt,
            vxx_today=vxx_today,
            final_sig_today=final_sig_today,
            ct_today=ct_today,
        )
        st.plotly_chart(fig_mon, width="stretch",
                        config=dict(displayModeBar=True, displaylogo=False,
                                    scrollZoom=False,
                                    modeBarButtonsToRemove=['select2d','lasso2d']))
    
        st.caption(
            f"Histórico: {bt.index[0].strftime('%Y-%m-%d')} → {last_date.strftime('%Y-%m-%d')} "
            f"({len(bt):,} días) · Parquet del repo · "
            f"Contango hoy: {ct_source} · "
            f"▲=Entrada  ▼🟡=Salida BB  ▼🔴=Salida CT"
        )
    
    
