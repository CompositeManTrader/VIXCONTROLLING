import streamlit as st

def render():
        st.markdown("""
        ### VIX Controller — Guía
    
        **Tab 1: Term Structure** — Réplica de VIXCentral.com
        - Datos scrapeados directamente de la tabla CBOE Delayed Quotes via **Playwright + Chromium**
        - Solo contratos mensuales (regex `^VX/[A-Z]\\d+$` — filtra weeklys como VX12, VX13, etc.)
        - Muestra columnas: **Last, Change, High, Low, Settlement, Volume** (como la tabla CBOE)
        - Tabla de contango/diferencia entre meses (estilo VIXCentral)
        - Month 7 to 4 contango
        - Auto-refresh cada 60 segundos
    
        **Tab 2: Monitor Operativo** — Señal BB × Contango
        - **BB Timing**: VXX < SMA(20) = LONG, VXX > BB Superior = EXIT
        - **Contango**: se alimenta automáticamente del term structure scrapeado
        - **Señal Final** = BB × Contango
        - Gráfico VXX + BB con zonas y flechas ENTRY/EXIT
    
        ---
    
        **Fuentes:**
        - `cboe.com/delayed_quotes/futures/future_quotes` — scrapeado con Playwright
        - Yahoo Finance — VIX spot, VXX, SVXY, SVIX, SPY
    
        **Para Streamlit Cloud necesitas:**
        - `packages.txt` con dependencias de Chromium
        - `requirements.txt` con playwright
        """)
    
