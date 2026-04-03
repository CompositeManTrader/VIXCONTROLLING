import streamlit as st
import pandas as pd
from core.data_fetchers import fetch_cot_vix
from core.charts import (build_cot_positioning_chart, build_cot_oi_chart,
                          build_cot_breakdown_chart)

def render():
    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#8B949E;
                padding:0.4rem 0 0.8rem;">
    Fuente: <b>CFTC Disaggregated COT Report</b> · Código VIX Futures: <b>1170E1</b> ·
    Publicación: martes ~15:30 ET con datos del martes anterior ·
    API: publicreporting.cftc.gov (gratuita, sin autenticación)
    </div>
    """, unsafe_allow_html=True)

    col_cot1, col_cot2 = st.columns([3, 1])
    with col_cot1:
        cot_weeks = st.slider("Semanas de historia", 26, 156, 104,
                              help="1 año = 52 semanas · 3 años = 156")
    with col_cot2:
        if st.button("🔄 Actualizar COT", key="btn_refresh_cot"):
            fetch_cot_vix.clear()
            st.rerun()

    with st.spinner("📋 Descargando COT de CFTC…"):
        cot_df = fetch_cot_vix(n_weeks=max(cot_weeks + 10, 156))

    if cot_df.empty:
        st.error("❌ No se pudieron obtener datos COT del CFTC.")
        st.info(
            "La API CFTC (publicreporting.cftc.gov) es pública y gratuita. "
            "Si falla, intenta de nuevo en unos minutos — el caché es de 6 horas."
        )
        return

    last_cot = cot_df.iloc[-1]
    last_date_cot = last_cot["date"].strftime("%Y-%m-%d") if pd.notna(last_cot["date"]) else "?"

    mm_net     = int(last_cot.get("net_mm", 0) or 0)
    mm_pct     = last_cot.get("net_mm_pct", None)
    mm_pctile  = last_cot.get("net_mm_pct_pctile", None)
    oi_val     = int(last_cot.get("oi", 0) or 0)
    dealer_net = int(last_cot.get("net_dealer", 0) or 0)
    comm_net   = int(last_cot.get("net_commercial", 0) or 0)

    if mm_pctile is not None:
        if mm_net > 0 and mm_pctile > 70:
            cot_signal = "⚡ MM NET LONG extremo — alta demanda de vol"
            cot_sig_clr = "var(--r)"
            cot_interp = ("Managed Money está net long VIX futures por encima del percentil 70 histórico.")
        elif mm_net > 0:
            cot_signal = "📈 MM NET LONG moderado"
            cot_sig_clr = "var(--y)"
            cot_interp = "Managed Money tiene posición neta long en VIX futures."
        elif mm_net < 0 and mm_pctile < 30:
            cot_signal = "✅ MM NET SHORT — complacencia elevada"
            cot_sig_clr = "var(--g)"
            cot_interp = "Managed Money está net short VIX futures — favorable para inverse vol."
        else:
            cot_signal = "➡️ Posicionamiento neutral"
            cot_sig_clr = "var(--b)"
            cot_interp = "Managed Money está cerca del equilibrio en futuros VIX."
    else:
        cot_signal  = "—"
        cot_sig_clr = "var(--dim)"
        cot_interp  = ""

    mm_pct_s    = f"{mm_pct:+.1f}% del OI" if mm_pct is not None else "—"
    mm_pctile_s = f"Pct {mm_pctile:.0f}°"   if mm_pctile is not None else "—"

    st.markdown(f"""
    <div class="mrow">
        <div class="mpill" style="min-width:180px">
            <div class="ml">Señal COT</div>
            <div style="font-family:'Inter',sans-serif;font-weight:700;font-size:0.9rem;
                        color:{cot_sig_clr}">{cot_signal}</div>
        </div>
        <div class="mpill">
            <div class="ml">Net MM · {last_date_cot}</div>
            <div class="mv {'up' if mm_net>=0 else 'dn'}">{mm_net:+,}</div>
        </div>
        <div class="mpill">
            <div class="ml">Net MM % OI</div>
            <div class="mv nt">{mm_pct_s}</div>
        </div>
        <div class="mpill">
            <div class="ml">Percentil histórico</div>
            <div class="mv nt">{mm_pctile_s}</div>
        </div>
        <div class="mpill">
            <div class="ml">Open Interest</div>
            <div class="mv nt">{oi_val:,}</div>
        </div>
        <div class="mpill">
            <div class="ml">Net Dealers</div>
            <div class="mv {'up' if dealer_net>=0 else 'dn'}">{dealer_net:+,}</div>
        </div>
        <div class="mpill">
            <div class="ml">Net Commercial</div>
            <div class="mv {'up' if comm_net>=0 else 'dn'}">{comm_net:+,}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if cot_interp:
        with st.expander("📊 Interpretación COT", expanded=True):
            st.markdown(cot_interp)
            st.markdown("""
**Guía de lectura:**
- **MM net LONG VIX** → especuladores apuestan a subida de vol → mercado defensivo
- **MM net SHORT VIX** → apuestan a vol baja → contango favorable para inverse vol
- **OI creciente + MM net short** → viento de cola para SVXY/SVIX
- El COT se publica **cada martes** con datos de la semana anterior
            """)

    st.markdown("<div style='border-top:1px solid #30363D;margin:0.5rem 0'></div>",
                unsafe_allow_html=True)

    try:
        fig_pos = build_cot_positioning_chart(cot_df, window=cot_weeks)
        if fig_pos.data:
            st.plotly_chart(fig_pos, use_container_width=True,
                            config=dict(displayModeBar=False))
    except Exception as e:
        st.error(f"Error chart posicionamiento: {e}")

    col_oi, col_bd = st.columns(2)
    with col_oi:
        try:
            fig_oi = build_cot_oi_chart(cot_df, window=cot_weeks)
            if fig_oi.data:
                st.plotly_chart(fig_oi, use_container_width=True,
                                config=dict(displayModeBar=False))
        except Exception as e:
            st.error(f"Error chart OI: {e}")

    with col_bd:
        try:
            fig_bd = build_cot_breakdown_chart(cot_df, window=min(cot_weeks, 104))
            if fig_bd.data:
                st.plotly_chart(fig_bd, use_container_width=True,
                                config=dict(displayModeBar=False))
        except Exception as e:
            st.error(f"Error chart breakdown: {e}")

    with st.expander("📋 Datos semanales COT"):
        show_cols = [c for c in
            ["date","oi","mm_long","mm_short","net_mm","net_mm_pct",
             "net_mm_pct_pctile","dealer_long","dealer_short","net_dealer",
             "net_commercial"]
            if c in cot_df.columns]
        st.dataframe(
            cot_df[show_cols].tail(cot_weeks).sort_values("date", ascending=False),
            use_container_width=True, hide_index=True,
        )

    st.caption(
        f"CFTC Disaggregated COT · VIX Futures (1170E1) · "
        f"Última semana: {last_date_cot} · Cache: 6h"
    )
