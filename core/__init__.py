from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import logging

CDMX_TZ = ZoneInfo("America/Mexico_City")

def now_cdmx():
    return datetime.now(CDMX_TZ)

C = {
    "bg": "#0D1117", "card": "#161B22", "border": "#30363D",
    "text": "#C9D1D9", "dim": "#8B949E", "bright": "#F0F6FC",
    "green": "#3FB950", "red": "#F85149", "yellow": "#D29922",
    "blue": "#58A6FF", "purple": "#BC8CFF", "cyan": "#39D2C0",
    "orange": "#F0883E", "white": "#FFFFFF",
    "green_bg": "#0B2E13", "red_bg": "#3B1218",
}

MN = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
      7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}

def cpct(p1, p2):
    if p1 and p2 and p1 > 0:
        return round((p2 - p1) / p1 * 100, 2)
    return None

def fv(v):
    return f"{v:.2f}" if v is not None and pd.notna(v) and v != 0 else chr(8212)

def vc(v):
    if v is None: return "nt"
    return "up" if v >= 0 else "dn"

def fp(v):
    if v is None: return chr(8212)
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"
