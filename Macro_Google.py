import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Sovereign Macro Engine", layout="wide")
st.title("Sovereign Macro Execution Engine")
st.caption("Execution > Prediction | Survival First")

# --------------------------------------------------
# API CONFIG
# --------------------------------------------------
api_key = st.secrets.get("FRED_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Enter FRED API Key", type="password")

if not api_key:
    st.warning("Enter FRED API Key")
    st.stop()

start_date = "2015-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

# --------------------------------------------------
# SERIES MAP
# --------------------------------------------------
# NOTE ON "DXY": DTWEXAFEGS is the Fed's free Nominal Advanced Foreign
# Economies Dollar Index -- a broad ~26-currency, trade-weighted basket,
# base year 2006=100. It is NOT the ICE US Dollar Index (DXY), which is a
# fixed 6-currency basket (EUR-dominated), base year 1973=100, and is
# proprietary/paid data. The two are highly correlated on % moves but their
# RAW LEVELS are not comparable -- do not read this index's level as if it
# were a DXY quote. We label it "USD Index (Fed Broad-AFE)" throughout and
# only ever use its % change (trend), never its level, in engine logic.
SERIES = {
    "USD_BROAD": "DTWEXAFEGS",   # proxy for USD strength, NOT ICE DXY
    "10Y": "DGS10",
    "FED": "WALCL",              # $ millions
    "RRP": "RRPONTSYD",          # $ billions  <-- different unit than FED/TGA
    "TGA": "WTREGEN",            # $ millions
    "CREDIT_SPREAD": "BAMLH0A0HYM2"
}

# --------------------------------------------------
# FETCH DATA
# --------------------------------------------------
@st.cache_data(ttl=86400)
def fetch(series):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        if "observations" not in data:
            st.warning(f"No observations returned for series '{series}'.")
            return pd.Series(dtype="float64")

        df = pd.DataFrame(data["observations"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        return df.dropna().set_index("date")["value"]

    except requests.exceptions.RequestException as e:
        st.warning(f"Network/API error fetching '{series}': {e}")
        return pd.Series(dtype="float64")
    except Exception as e:
        st.warning(f"Unexpected error fetching '{series}': {e}")
        return pd.Series(dtype="float64")

# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------
usd_broad = fetch(SERIES["USD_BROAD"])
y10 = fetch(SERIES["10Y"])
fed = fetch(SERIES["FED"])
rrp = fetch(SERIES["RRP"])
tga = fetch(SERIES["TGA"])
credit_spread = fetch(SERIES["CREDIT_SPREAD"])

# --------------------------------------------------
# ALIGN LIQUIDITY DATA (UNIT FIX: RRP is in $B, FED/TGA are in $M)
# --------------------------------------------------
if fed.empty or rrp.empty or tga.empty:
    st.error("One or more liquidity series (FED/RRP/TGA) failed to load. "
             "Liquidity metrics will be unavailable.")

rrp_millions = rrp * 1000  # convert $B -> $M so all three series share units

df_liq = pd.concat([fed, rrp_millions, tga], axis=1)
df_liq.columns = ["fed", "rrp", "tga"]
df_liq = df_liq.ffill().dropna()

# --------------------------------------------------
# ALIGN ALL DAILY SIGNALS TO A COMMON CALENDAR
# --------------------------------------------------
# Previously usd_broad / y10 / credit_spread were each read independently
# with .iloc[-1], so "latest" could silently mean different calendar dates
# across metrics (they publish on different schedules / with different
# reporting lags). Reindex everything onto one shared daily index and
# forward-fill, so every "latest" value reflects the same as-of date.
common_index = df_liq.index
for s in (usd_broad, y10, credit_spread):
    if not s.empty:
        common_index = common_index.union(s.index)
common_index = common_index.sort_values()

def align(s):
    if s.empty:
        return s
    return s.reindex(common_index).ffill()

usd_broad_a = align(usd_broad)
y10_a = align(y10)
credit_spread_a = align(credit_spread)

as_of_date = common_index.max() if len(common_index) else None

# --------------------------------------------------
# LIQUIDITY ENGINE (SMOOTHED)
# --------------------------------------------------
net_liquidity = df_liq["fed"] - df_liq["rrp"] - df_liq["tga"]  # all in $M now

liq_impulse_raw = net_liquidity.pct_change(30)
liq_impulse = liq_impulse_raw.rolling(5).mean().dropna()

liq_trend = liq_impulse.iloc[-1] if not liq_impulse.empty else 0

# --------------------------------------------------
# CORE SIGNALS
# --------------------------------------------------
# NOTE: window/smoothing choices below are intentionally standardized
# (30-day % change, 5-day rolling smooth) across every trend signal so
# that liq_trend, yield_trend, dxy_trend, and credit_trend_val are all
# measured on the same time basis before being compared/combined in the
# regime and system-phase classifiers below. (Previously yield_trend used
# an unsmoothed 60-day window while liquidity/credit used smoothed 30-day
# windows -- an apples-to-oranges comparison.)
TREND_WINDOW = 30
SMOOTH_WINDOW = 5

def trend(series, window=TREND_WINDOW, smooth=SMOOTH_WINDOW):
    if series.empty:
        return 0
    raw = series.pct_change(window)
    smoothed = raw.rolling(smooth).mean().dropna()
    if smoothed.empty:
        return 0
    return smoothed.iloc[-1]

yield_trend = trend(y10_a)
dxy_trend = trend(usd_broad_a)          # "dxy_trend" kept as variable name
credit_trend_val = trend(credit_spread_a)

# --------------------------------------------------
# ACTUAL LEVEL VALUES
# --------------------------------------------------
latest_yield = y10_a.iloc[-1] if not y10_a.empty else 0
latest_usd_broad = usd_broad_a.iloc[-1] if not usd_broad_a.empty else 0
latest_credit = credit_spread_a.iloc[-1] if not credit_spread_a.empty else 0
latest_liquidity = net_liquidity.iloc[-1] if not net_liquidity.empty else 0

# --------------------------------------------------
# CREDIT STATE
# --------------------------------------------------
def credit_state(val):
    if val > 0.15:
        return "STRESS SPIKE"
    elif val > 0:
        return "WIDENING"
    else:
        return "STABLE"

credit_status = credit_state(credit_trend_val)

# --------------------------------------------------
# SYSTEM PHASE
# --------------------------------------------------
def detect_system_phase(liq, dxy, credit):

    if liq < 0 and dxy > 0 and credit == "WIDENING":
        return "FRACTURE"

    if liq < 0 and dxy > 0 and credit == "STRESS SPIKE":
        return "SYSTEM BREAK"

    return "NORMAL"

system_phase = detect_system_phase(liq_trend, dxy_trend, credit_status)

# --------------------------------------------------
# REGIME
# --------------------------------------------------
def classify_regime(y, d):
    if y > 0 and d > 0:
        return "QT"
    elif y < 0 and d < 0:
        return "SOFT_PIVOT"
    elif y < 0 and d > 0:
        return "HARD_PIVOT"
    else:
        return "TRANSITION"

regime = classify_regime(yield_trend, dxy_trend)

# --------------------------------------------------
# SAFER EARLY PIVOT (FILTERED)
# --------------------------------------------------
# BUG FIX: original condition required regime == "QT" (which by
# classify_regime's own definition requires yield_trend > 0) AND
# yield_trend < 0 in the same branch -- a contradiction that could never
# be true, so EARLY_PIVOT was dead code. An "early pivot" is better
# understood as liquidity expanding while yields/dollar direction are
# still ambiguous (i.e. regime == "TRANSITION"), so we gate on that
# instead.
if liq_trend > 0.01 and yield_trend < 0 and regime == "TRANSITION":
    regime = "EARLY_PIVOT"

# --------------------------------------------------
# DCA LOGIC
# --------------------------------------------------
if liq_trend > 0.05:
    dca_mode = "HIGH DCA"
elif liq_trend > 0:
    dca_mode = "MEDIUM DCA"
else:
    dca_mode = "LOW / PAUSE"

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def arrow(x):
    return "↑" if x > 0 else "↓" if x < 0 else "→"

def format_liquidity(x_millions):
    # BUG FIX: FRED liquidity series are denominated in $ millions already.
    # The old version compared that millions-scale number directly against
    # 1e9 / 1e12 thresholds meant for raw dollars, so it could never reach
    # the "B" or "T" branches and always printed misleadingly small "M"
    # values. Convert to raw dollars first, then bucket.
    x = x_millions * 1e6
    if abs(x) >= 1e12:
        return f"${x/1e12:.2f}T"
    elif abs(x) >= 1e9:
        return f"${x/1e9:.0f}B"
    return f"${x/1e6:.0f}M"

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
if as_of_date is not None:
    st.caption(f"Data as of {as_of_date.strftime('%Y-%m-%d')} (forward-filled to common calendar)")

st.subheader("Macro Chokepoints")

c1, c2, c3, c4 = st.columns(4)

c1.metric("Liquidity",
          format_liquidity(latest_liquidity),
          f"{liq_trend*100:.2f}% {arrow(liq_trend)}")

c2.metric("10Y Yield",
          f"{latest_yield:.2f}%",
          f"{yield_trend*100:.2f}% {arrow(yield_trend)}")

c3.metric("USD Index (Fed Broad-AFE)",
          f"{latest_usd_broad:.2f}",
          f"{dxy_trend*100:.2f}% {arrow(dxy_trend)}",
          help="Fed's Nominal Advanced Foreign Economies Dollar Index "
               "(DTWEXAFEGS) -- a free proxy for broad USD strength. "
               "NOT the ICE US Dollar Index (DXY): different currency "
               "basket, different weights, different base year. Trend "
               "(% change) is comparable in spirit; the raw level is not "
               "the same number you'd see quoted as 'DXY' elsewhere.")

c4.metric("Credit Spread",
          f"{latest_credit:.2f}%",
          f"{credit_trend_val*100:.2f}% {arrow(credit_trend_val)}")

# --------------------------------------------------
# SYSTEM STATE
# --------------------------------------------------
st.subheader("System State")

c5, c6, c7 = st.columns(3)
c5.metric("Regime", regime)
c6.metric("Credit Condition", credit_status)
c7.metric("System Phase", system_phase)

# --------------------------------------------------
# EXECUTION
# --------------------------------------------------
st.subheader("Execution")

col1, col2 = st.columns(2)
col1.metric("DCA Mode", dca_mode)
col2.metric("Risk Status", "RISK OFF" if system_phase == "SYSTEM BREAK" else "ACTIVE")
