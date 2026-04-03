import streamlit as st
import pandas as pd
from core import fv, vc, fp, cpct, MN
from core.charts import build_term_chart

def render(df_vx, vix_spot, etps, m1p, m2p, front_ct, SHOW_PREV, SHOW_TABLE, N_MONTHS):
        vix_p = vix_spot['price'] if vix_spot else None
    
        # Metrics
        last_price_col = df_vx['Price'].tolist() if not df_vx.empty else []
        total_ct = cpct(vix_p, last_price_col[-1]) if vix_p and last_price_col else None
        spot_m1 = cpct(vix_p, m1p)
    
        m1_lbl = ""
        m1_dte = "?"
        m2_lbl = ""
        if not df_vx.empty:
            exp1 = df_vx['Expiration'].iloc[0]
            if pd.notna(exp1):
                m1_lbl = MN.get(exp1.month, "")
                m1_dte = df_vx['DTE'].iloc[0] if 'DTE' in df_vx.columns else "?"
            if len(df_vx) > 1:
                exp2 = df_vx['Expiration'].iloc[1]
                if pd.notna(exp2):
                    m2_lbl = MN.get(exp2.month, "")
    
        st.markdown(f"""
        <div class="mrow">
            <div class="mpill"><div class="ml">VIX Index</div><div class="mv nt">{fv(vix_p)}</div></div>
            <div class="mpill"><div class="ml">M1 · {m1_lbl} · {m1_dte} DTE</div><div class="mv nt">{fv(m1p)}</div></div>
            <div class="mpill"><div class="ml">M2 · {m2_lbl}</div><div class="mv nt">{fv(m2p)}</div></div>
            <div class="mpill"><div class="ml">VIX → M1</div><div class="mv {vc(spot_m1)}">{fp(spot_m1)}</div></div>
            <div class="mpill"><div class="ml">M1 → M2 Contango</div><div class="mv {vc(front_ct)}">{fp(front_ct)}</div></div>
            <div class="mpill"><div class="ml">Total Curve</div><div class="mv {vc(total_ct)}">{fp(total_ct)}</div></div>
        </div>
        """, unsafe_allow_html=True)
    
        # Chart
        fig = build_term_chart(vix_spot, df_vx, show_prev=SHOW_PREV)
        st.plotly_chart(fig, width="stretch", config=dict(displayModeBar=True, displaylogo=False))
    
        # Contango & Difference table (VIXCentral style)
        if len(df_vx) >= 2:
            ct_cells = ""
            diff_cells = ""
            for i in range(len(df_vx) - 1):
                n = i + 1
                p1 = df_vx['Price'].iloc[i]
                p2 = df_vx['Price'].iloc[i + 1]
                ct = cpct(p1, p2)
                diff = round(p2 - p1, 2) if pd.notna(p1) and pd.notna(p2) and p1 > 0 and p2 > 0 else None
                ct_cls = "pos" if ct and ct >= 0 else "neg"
                diff_cls = "pos" if diff and diff >= 0 else "neg"
                ct_cells += f'<td>{n}</td><td class="{ct_cls}">{fp(ct)}</td>'
                diff_cells += f'<td>{n}</td><td class="{diff_cls}">{fv(diff)}</td>'
    
            m74_ct, m74_diff = None, None
            if len(df_vx) >= 7:
                p4 = df_vx['Price'].iloc[3]
                p7 = df_vx['Price'].iloc[6]
                if pd.notna(p4) and pd.notna(p7) and p4 > 0 and p7 > 0:
                    m74_ct = cpct(p4, p7)
                    m74_diff = round(p7 - p4, 2)
    
            st.markdown(f"""
            <table class="ctx">
            <tr><td class="hdr-cell">% Contango</td>{ct_cells}</tr>
            <tr><td class="hdr-cell">Difference</td>{diff_cells}</tr>
            </table>
            """, unsafe_allow_html=True)
    
            if m74_ct is not None:
                m74_cls = "pos" if m74_ct >= 0 else "neg"
                st.markdown(f"""
                <table class="ctx" style="width:auto;margin-top:4px;">
                <tr><td class="hdr-cell">Month 7 to 4 contango</td>
                <td class="{m74_cls}">{fp(m74_ct)}</td><td class="{m74_cls}">{fv(m74_diff)}</td></tr>
                </table>""", unsafe_allow_html=True)
    
        # Data table
        if SHOW_TABLE and not df_vx.empty:
            rows = ""
            prev_p = vix_p
            for _, r in df_vx.iterrows():
                sym = r.get('Symbol', '')
                exp = r.get('Expiration')
                exp_s = exp.strftime('%m/%d/%Y') if pd.notna(exp) else "—"
                last = r.get('Last', 0)
                chg = r.get('Change', 0)
                hi = r.get('High', 0)
                lo = r.get('Low', 0)
                settle = r.get('Settlement', 0)
                vol = r.get('Volume', 0)
                price = r.get('Price', 0)
                dte = r.get('DTE', '')
    
                ct = cpct(prev_p, price) if prev_p and pd.notna(price) and price > 0 else None
                chg_c = "color:var(--g)" if pd.notna(chg) and chg > 0 else "color:var(--r)" if pd.notna(chg) and chg < 0 else ""
                ct_c = "color:var(--g)" if ct and ct >= 0 else "color:var(--r)" if ct else ""
                last_s = f"{last:.2f}" if pd.notna(last) and last > 0 else "—"
                chg_s = f"{chg:+.3f}" if pd.notna(chg) and chg != 0 else "—"
                hi_s = f"{hi:.2f}" if pd.notna(hi) and hi > 0 else "—"
                lo_s = f"{lo:.2f}" if pd.notna(lo) and lo > 0 else "—"
                settle_s = f"{settle:.4f}" if pd.notna(settle) and settle > 0 else "—"
                vol_s = f"{int(vol):,}" if pd.notna(vol) and vol > 0 else "0"
    
                rows += f"""<tr>
                    <td style="color:var(--b);font-weight:600">{sym}</td>
                    <td>{exp_s}</td>
                    <td style="font-weight:600">{last_s}</td>
                    <td style="{chg_c}">{chg_s}</td>
                    <td>{hi_s}</td><td>{lo_s}</td>
                    <td>{settle_s}</td>
                    <td style="{ct_c}">{fp(ct) if ct else '—'}</td>
                    <td>{dte}</td>
                    <td>{vol_s}</td>
                </tr>"""
                if pd.notna(price) and price > 0:
                    prev_p = price
    
            st.markdown(f"""
            <table class="dtbl">
                <thead><tr><th>Symbol</th><th>Expiration</th><th>Last</th><th>Change</th>
                <th>High</th><th>Low</th><th>Settlement</th><th>Contango</th><th>DTE</th><th>Volume</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>""", unsafe_allow_html=True)
    
        if df_vx.empty:
            st.warning("⚠️ No se pudieron obtener precios de futuros VIX del CBOE.")
            if not pw_ready:
                st.error("❌ Playwright/Chromium no se pudo inicializar. Verifica packages.txt y requirements.txt")
            st.info("💡 La página CBOE carga datos por JavaScript. Se necesita Playwright + Chromium para renderizarla.")
    
        if not df_vx.empty:
            scraped = df_vx['Scraped_At'].iloc[0] if 'Scraped_At' in df_vx.columns else "?"
            st.caption(f"Contratos: {len(df_vx)} mensuales · Scraped: {scraped} · CBOE Delayed Quotes")
    
    
