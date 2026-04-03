"""
VIX Controller — Bloomberg-Style Volatility Intelligence Platform
Modular architecture: app.py → tabs/ + core/
"""
import streamlit as st
import time
from datetime import datetime

st.set_page_config(page_title="VIX Controller", page_icon="🔴", layout="wide",
                   initial_sidebar_state="collapsed")

# ── Core imports ──
from core import now_cdmx, cpct, fv, vc, fp
from core.styles import inject_css
from core.data_fetchers import (check_playwright_installed, scrape_cboe_futures,
                                 fetch_vix_spot, fetch_etps)

# ── Inject CSS ──
inject_css()

# ── Playwright check (once per deployment) ──
pw_ready = check_playwright_installed()

# ── Auto-refresh ──
REFRESH_INTERVAL = 60

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

elapsed = time.time() - st.session_state.last_refresh
if elapsed > REFRESH_INTERVAL:
    st.session_state.last_refresh = time.time()
    st.cache_data.clear()
    st.rerun()

st.components.v1.html(f"""
<script>
(function() {{
    var remaining = {REFRESH_INTERVAL};
    var timer = setInterval(function() {{
        remaining--;
        var el = window.parent.document.getElementById('refresh-countdown');
        if (el) el.textContent = remaining + 's';
        if (remaining <= 0) {{
            clearInterval(timer);
            window.parent.location.reload();
        }}
    }}, 1000);
}})();
</script>
""", height=0)

# ── Header ──
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
        Auto-refresh in <span id="refresh-countdown" style="color:#F7931A;font-weight:600">{REFRESH_INTERVAL}s</span> · Source: CBOE Delayed Quotes
    </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    N_MONTHS = st.slider("Max futures months", 4, 12, 8)
    SHOW_PREV = st.checkbox("Show previous day", True)
    SHOW_TABLE = st.checkbox("Show data table", True)
    if st.button("🔄 Refresh Now"):
        st.session_state.last_refresh = time.time()
        st.cache_data.clear()
        st.rerun()

# ── Fetch shared data ──
with st.spinner("🌐 Scraping CBOE delayed quotes…"):
    df_vx = scrape_cboe_futures()

# Sidebar debug
with st.sidebar:
    debug_msg = st.session_state.get("scrape_debug", "")
    if debug_msg:
        if debug_msg.startswith("❌"):
            st.error(debug_msg)
        else:
            st.info(f"🔍 {debug_msg}")

vix_spot = fetch_vix_spot()
etps = fetch_etps()

# Limit months
if not df_vx.empty and len(df_vx) > N_MONTHS:
    df_vx = df_vx.head(N_MONTHS).reset_index(drop=True)

# Extract M1/M2
m1p = df_vx['Price'].iloc[0] if not df_vx.empty and not df_vx['Price'].isna().iloc[0] else None
m2p = df_vx['Price'].iloc[1] if len(df_vx) > 1 and not df_vx['Price'].isna().iloc[1] else None
front_ct = cpct(m1p, m2p)

# ══════════════════════════════════════════════════════════════
# TABS — each tab is a separate module
# ══════════════════════════════════════════════════════════════
import tabs.term_structure
import tabs.monitor
import tabs.edge_analytics
import tabs.vol_surface
import tabs.cot
import tabs.recommendations
import tabs.help

tab1, tab2, tab_edge, tab_skew, tab_cot, tab3, tab4 = st.tabs([
    "📈  Term Structure",
    "🎯  Monitor Operativo",
    "🔬  Edge Analytics",
    "📐  Vol Skew & Surface",
    "📋  COT Positioning",
    "💡  Recomendaciones",
    "ℹ️  Help",
])

with tab1:
    tabs.term_structure.render(df_vx, vix_spot, etps, m1p, m2p, front_ct,
                                SHOW_PREV, SHOW_TABLE, N_MONTHS)

with tab2:
    tabs.monitor.render(m1p, m2p, df_vx)

with tab_edge:
    tabs.edge_analytics.render()

with tab_skew:
    tabs.vol_surface.render()

with tab_cot:
    tabs.cot.render()

with tab3:
    tabs.recommendations.render()

with tab4:
    tabs.help.render()

# ── Footer ──
st.markdown(f"""
<div style="text-align:center;padding:0.8rem 0 0.3rem;border-top:1px solid #30363D;margin-top:1rem;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.6rem;color:#484F58;">
        VIX CONTROLLER · Alberto Alarcón González · Not financial advice
    </span>
</div>""", unsafe_allow_html=True)
