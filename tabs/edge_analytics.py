import streamlit as st
import pandas as pd
import numpy as np
from core.data_fetchers import load_master_parquet, fetch_edge_extra
from core.charts import (compute_edge_analytics, build_vrp_chart, build_rv_chart,
                          build_roll_yield_chart, build_vvix_ratio_chart,
                          build_skew_chart as build_edge_skew_chart,
                          build_credit_chart)

def render():
    
        if 'df_master' not in dir() or df_master.empty:
            df_master_edge = load_master_parquet()
        else:
            df_master_edge = df_master
    
        if df_master_edge.empty:
            st.error("No se pudo cargar el Master para Edge Analytics.")
        else:
            with st.spinner("Calculando edge analytics..."):
                edge_extra = fetch_edge_extra()
                edge = compute_edge_analytics(df_master_edge, edge_extra)
    
            if 'bt' not in edge:
                st.error("Datos insuficientes para edge analytics.")
            else:
                ebt = edge['bt']
                last_e = ebt.iloc[-1]
    
                def ecard(label, val, sub, clr="nt"):
                    c = "var(--g)" if clr == "up" else "var(--r)" if clr == "dn" else "var(--b)"
                    return (f'<div class="mpill"><div class="ml">{label}</div>'
                            f'<div class="mv" style="color:{c}">{val}</div>'
                            f'<div style="font-size:0.6rem;color:var(--dim)">{sub}</div></div>')
    
                vrp_val = last_e.get('VRP', np.nan)
                vrp_pct = edge.get('vrp_percentile', '?')
                rv20_val = last_e.get('RV20', np.nan)
                ry_val = last_e.get('Roll_Yield', np.nan)
                vvix_r = last_e.get('VVIX_VIX', np.nan)
                skew_val = last_e.get('SKEW', np.nan)
    
                vrp_str = f"{vrp_val:+.1f}" if pd.notna(vrp_val) else "N/A"
                vrp_clr = "up" if pd.notna(vrp_val) and vrp_val > 2 else "dn" if pd.notna(vrp_val) and vrp_val < 0 else "nt"
                ry_str = f"{ry_val:+.1f}%" if pd.notna(ry_val) else "N/A"
                ry_clr = "up" if pd.notna(ry_val) and ry_val > 0 else "dn" if pd.notna(ry_val) and ry_val < 0 else "nt"
                vvix_str = f"{vvix_r:.2f}" if pd.notna(vvix_r) else "N/A"
                vvix_clr = "dn" if pd.notna(vvix_r) and vvix_r > 6 else "up" if pd.notna(vvix_r) and vvix_r < 5 else "nt"
                skew_str = f"{skew_val:.0f}" if pd.notna(skew_val) else "N/A"
                skew_clr = "dn" if pd.notna(skew_val) and skew_val > 150 else "up" if pd.notna(skew_val) and skew_val < 130 else "nt"
    
                st.markdown(f"""<div class="mrow">
                    {ecard("VRP (IV-RV)", vrp_str, f"P{vrp_pct} hist" if vrp_pct != '?' else "", vrp_clr)}
                    {ecard("RV20 (SPX)", f"{rv20_val:.1f}" if pd.notna(rv20_val) else "N/A", "Realized Vol 20d", "nt")}
                    {ecard("Roll Yield", ry_str, "Carry anualizado", ry_clr)}
                    {ecard("VVIX/VIX", vvix_str, "> 6 = peligro", vvix_clr)}
                    {ecard("SKEW", skew_str, "> 150 = extremo", skew_clr)}
                    {ecard("VIX", f"{last_e['VIX_Close']:.1f}", f"RV20: {rv20_val:.1f}" if pd.notna(rv20_val) else "", "nt")}
                </div>""", unsafe_allow_html=True)
    
                # Calendario de eventos
                upcoming = edge.get('upcoming_events', [])
                if upcoming:
                    ev_html = ""
                    for name, dt, days in upcoming:
                        ev_clr = "var(--r)" if days <= 2 else "var(--y)" if days <= 5 else "var(--dim)"
                        ev_tag = "HOY" if days == 0 else f"en {days}d"
                        ev_html += (f'<span style="background:var(--card);border:1px solid {ev_clr};'
                                   f'border-radius:4px;padding:0.2rem 0.6rem;margin-right:0.4rem;'
                                   f'font-family:JetBrains Mono;font-size:0.75rem;color:{ev_clr}">'
                                   f'{name} {dt.strftime("%b %d")} · {ev_tag}</span>')
                    st.markdown(f'<div style="margin:0.4rem 0 0.8rem">{ev_html}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="font-family:JetBrains Mono;font-size:0.75rem;color:#3FB950;'
                                'margin:0.4rem 0 0.8rem">Sin eventos macro en los proximos 14 dias</div>',
                                unsafe_allow_html=True)
    
                # Edge Verdict
                warnings_e = []
                if pd.notna(vrp_val) and vrp_val < 0:
                    warnings_e.append("VRP negativo — estas pagando por estar posicionado")
                if pd.notna(vvix_r) and vvix_r > 6:
                    warnings_e.append("VVIX/VIX > 6 — dealers anticipan spike")
                if pd.notna(ry_val) and ry_val < 0:
                    warnings_e.append("Roll Yield negativo — backwardation erosiona el carry")
                if pd.notna(skew_val) and skew_val > 150:
                    warnings_e.append("SKEW extremo — alta demanda de proteccion")
                if any(ev[2] <= 2 for ev in upcoming):
                    warnings_e.append("Evento macro inminente — considerar reducir exposicion")
    
                if len(warnings_e) >= 3:
                    verdict, v_clr, v_bg = "EDGE COMPROMETIDO", "var(--r)", "var(--rbg)"
                elif len(warnings_e) >= 1:
                    verdict, v_clr, v_bg = "EDGE ACTIVO — CON PRECAUCION", "var(--y)", "#3D2E00"
                else:
                    verdict, v_clr, v_bg = "EDGE SALUDABLE", "var(--g)", "var(--gbg)"
    
                st.markdown(f"""<div style="background:{v_bg};border:1px solid {v_clr};
                    border-radius:6px;padding:0.6rem 1rem;margin-bottom:0.8rem">
                    <span style="font-family:Inter;font-weight:800;font-size:1rem;color:{v_clr}">{verdict}</span>
                    <span style="font-family:JetBrains Mono;font-size:0.7rem;color:var(--dim);margin-left:1rem">
                    {len(warnings_e)} warning{'s' if len(warnings_e) != 1 else ''}</span>
                </div>""", unsafe_allow_html=True)
                for w in warnings_e:
                    st.warning(w)
    
                st.markdown("<div style='border-top:1px solid #30363D;margin:0.6rem 0'></div>",
                            unsafe_allow_html=True)
    
                # Charts
                try:
                    st.plotly_chart(build_vrp_chart(ebt), width="stretch", config=dict(displayModeBar=False))
                except Exception as e:
                    st.error(f"Error VRP: {e}")
    
                try:
                    st.plotly_chart(build_rv_chart(ebt), width="stretch", config=dict(displayModeBar=False))
                except Exception as e:
                    st.error(f"Error RV: {e}")
    
                col_ry, col_vv = st.columns(2)
                with col_ry:
                    try:
                        st.plotly_chart(build_roll_yield_chart(ebt), width="stretch", config=dict(displayModeBar=False))
                    except Exception as e:
                        st.error(f"Error Roll Yield: {e}")
                with col_vv:
                    try:
                        st.plotly_chart(build_vvix_ratio_chart(ebt), width="stretch", config=dict(displayModeBar=False))
                    except Exception as e:
                        st.error(f"Error VVIX: {e}")
    
                col_sk, col_cr = st.columns(2)
                with col_sk:
                    try:
                        fig_sk = build_skew_chart(ebt)
                        if fig_sk.data:
                            st.plotly_chart(fig_sk, width="stretch", config=dict(displayModeBar=False))
                        else:
                            st.info("SKEW data no disponible")
                    except Exception as e:
                        st.error(f"Error SKEW: {e}")
                with col_cr:
                    try:
                        fig_cr = build_credit_chart(ebt)
                        if fig_cr.data:
                            st.plotly_chart(fig_cr, width="stretch", config=dict(displayModeBar=False))
                        else:
                            st.info("Credit spread data no disponible")
                    except Exception as e:
                        st.error(f"Error Credit: {e}")
    
                st.caption(f"Edge Analytics · Ventana: 1 ano · "
                           f"Fuentes: Master Parquet + Yahoo Finance (SKEW, HYG, IEF)")
    
    
