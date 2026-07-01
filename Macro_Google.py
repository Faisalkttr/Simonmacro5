import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# --------------------------------------------------
# PAGE CONFIG & ARCHITECTURE
# --------------------------------------------------
st.set_page_config(page_title="Sovereign Macro Engine v2", layout="wide")
st.title("Sovereign Macro Execution Engine")
st.caption("System State Framework | Front-Running the Central Bank Reaction Function")

# --------------------------------------------------
# SECURE API CONFIG
# --------------------------------------------------
api_key = st.secrets.get("FRED_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Enter FRED API Key", type="password")

if not api_key:
    st.warning("Please provide a valid FRED API Key to mount the macro engine.")
    st.stop()

start_date = "2015-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

# --------------------------------------------------
# MACRO TICKER MAP
# --------------------------------------------------
SERIES = {
    "DXY": "DTWEXAFEGS",       # Nominal Advanced Foreign Economies Dollar Index
    "10Y": "DGS10",            # 10-Year Treasury Constant Maturity Rate
    "FED": "WALCL",            # Federal Reserve Total Assets
    "RRP": "RRPONTSYD",        # Overnight Reverse Repurchase Agreements
    "TGA": "WTREGEN",          # Treasury General Account
    "CREDIT_SPREAD": "BAMLH0A0HYM2"  # ICE BofA High Yield Master II Option-Adjusted Spread
}

# --------------------------------------------------
# HIGH-UTILITY DATA INGESTION
# --------------------------------------------------
@st.cache_data(ttl=86400)
def fetch_macro_series(series_id, start, end, api_token):
    """Fetches raw observations from the FRED API and structures into a clean Series."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_token,
        "file_type": "json",
        "observation_start": start,
        "observation_end": end
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "observations" not in data:
            return pd.Series(dtype="float64")
            
        df = pd.DataFrame(data["observations"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().set_index("date")["value"]
    except Exception:
        return pd.Series(dtype="float64")

# Execute Pipeline Ingestion
dxy_raw = fetch_macro_series(SERIES["DXY"], start_date, end_date, api_key)
y10_raw = fetch_macro_series(SERIES["10Y"], start_date, end_date, api_key)
fed_raw = fetch_macro_series(SERIES["FED"], start_date, end_date, api_key)
rrp_raw = fetch_macro_series(SERIES["RRP"], start_date, end_date, api_key)
tga_raw = fetch_macro_series(SERIES["TGA"], start_date, end_date, api_key)
credit_raw = fetch_macro_series(SERIES["CREDIT_SPREAD"], start_date, end_date, api_key)

# --------------------------------------------------
# TIME-SERIES NORMALIZATION & COHERENCY LAYER
# --------------------------------------------------
# Consolidate raw variables into a singular frame to preserve exact temporal index alignment
df_raw = pd.concat([fed_raw, rrp_raw, tga_raw, y10_raw, dxy_raw, credit_raw], axis=1)
df_raw.columns = ["fed", "rrp", "tga", "y10", "dxy", "credit"]

# Forward-fill high-frequency daily values to cleanly meet weekly balances before resampling
df_daily = df_raw.ffill()

# Eliminate temporal distortion: Resample everything to uniform Weekly Last metrics
df_weekly = df_daily.resample("W").last().dropna()

# --------------------------------------------------
# QUANTITATIVE LIQUIDITY & ACCELERATION ENGINE
# --------------------------------------------------
# Calculate Net Domestic Liquidity Level
df_weekly["net_liquidity"] = df_weekly["fed"] - df_weekly["rrp"] - df_weekly["tga"]

# Rate of Change (Impulse): 6-week lookback on a normalized weekly framework
df_weekly["liq_impulse"] = df_weekly["net_liquidity"].pct_change(6)

# Velocity / Acceleration (Second Derivative): Are central banks injecting faster or rolling over?
df_weekly["liq_acceleration"] = df_weekly["liq_impulse"].diff(1)

# Rolling Historical Percentiles for Dynamic Regime Calibration
df_weekly["liq_percentile"] = df_weekly["liq_impulse"].rank(pct=True)

# --------------------------------------------------
# CONFIRMATION MATRIX TRENDS (Absolute Difference for Yields/Spreads)
# --------------------------------------------------
df_weekly["yield_trend"] = df_weekly["y10"].diff(6)          # Absolute change in percentage points
df_weekly["dxy_trend"] = df_weekly["dxy"].pct_change(6)      # Percentage change for currency indexes
df_weekly["credit_trend"] = df_weekly["credit"].diff(6)      # Absolute spread widening/narrowing

df_weekly = df_weekly.dropna()

# Extract final state indicators from the coherent index
current_liq_impulse = df_weekly["liq_impulse"].iloc[-1]
current_liq_accel = df_weekly["liq_acceleration"].iloc[-1]
current_liq_pct = df_weekly["liq_percentile"].iloc[-1]

current_yield_trend = df_weekly["yield_trend"].iloc[-1]
current_dxy_trend = df_weekly["dxy_trend"].iloc[-1]
current_credit_trend = df_weekly["credit_trend"].iloc[-1]

latest_net_liq = df_weekly["net_liquidity"].iloc[-1]
latest_y10 = df_weekly["y10"].iloc[-1]
latest_dxy = df_weekly["dxy"].iloc[-1]
latest_credit = df_weekly["credit"].iloc[-1]

# --------------------------------------------------
# SYSTEM STATE MACHINES (State-Based Execution)
# --------------------------------------------------
def determine_credit_state(spread_diff, spread_level):
    """Evaluates systemic credit conditions using velocity and absolute boundaries."""
    if spread_diff > 0.40 or spread_level > 5.5:
        return "STRESS SPIKE"
    elif spread_diff > 0:
        return "WIDENING"
    else:
        return "STABLE"

credit_status = determine_credit_state(current_credit_trend, latest_credit)

def detect_system_phase(liq_imp, dxy_t, credit_st):
    """Calculates systemic structural integrity based on liquidity constraints."""
    if credit_st == "STRESS SPIKE":
        return "SYSTEM BREAK"
    if liq_imp > 0 and dxy_t < 0:
        return "LIQUIDITY EXPANSION"
    if liq_imp < 0 and dxy_t > 0:
        return "LIQUIDITY CONTRACTION"
    return "TRANSITION"

system_phase = detect_system_phase(current_liq_impulse, current_dxy_trend, credit_status)

def classify_regime(y_trend, d_trend, liq_imp):
    """Evaluates macro regimes safely bypassing mutually exclusive parameter loops."""
    if liq_imp > 0.01 and y_trend < 0:
        return "EARLY_PIVOT"
    if y_trend > 0 and d_trend > 0:
        return "QT"
    if y_trend < 0 and d_trend < 0:
        return "SOFT_PIVOT"
    if y_trend < 0 and d_trend > 0:
        return "HARD_PIVOT"
    return "TRANSITION"

regime = classify_regime(current_yield_trend, current_dxy_trend, current_liq_impulse)

# --------------------------------------------------
# DYNAMIC ALLOCATION & GRADIENT RISK LAYERS
# --------------------------------------------------
# DCA Mode strictly driven by rolling historical percentiles
if current_liq_pct >= 0.80:
    dca_mode = "HIGH DCA (Aggressive Accumulation)"
elif current_liq_pct >= 0.30:
    dca_mode = "MEDIUM DCA (Steady Build)"
else:
    dca_mode = "LOW / PAUSE (Capital Preservation)"

# Gradient Defensive Matrix
if credit_status == "STRESS SPIKE" or system_phase == "SYSTEM BREAK":
    risk_status = "MAX DEFENSIVE"
elif current_liq_impulse < 0 or current_liq_accel < 0:
    risk_status = "DEFENSIVE"
elif current_liq_impulse > 0 and current_dxy_trend < 0:
    risk_status = "RISK ON"
else:
    risk_status = "NEUTRAL"

# --------------------------------------------------
# VISUAL UI ENGINE (Streamlit Output Template)
# --------------------------------------------------
def arrow(x):
    return "↑" if x > 0 else "↓" if x < 0 else "→"

def format_liquidity(x):
    if abs(x) >= 1e12: return f"{x/1e12:.2f}T"
    if abs(x) >= 1e9: return f"{x/1e9:.0f}B"
    return f"{x/1e6:.0f}M"

st.subheader("Macro Chokepoints")
m1, m2, m3, m4 = st.columns(4)

m1.metric("Net Liquidity", format_liquidity(latest_net_liq), f"Pctile: {current_liq_pct*100:.0f}%")
m2.metric("10Y Treasury Yield", f"{latest_y10:.2f}%", f"{current_yield_trend*100:.0f} bps {arrow(current_yield_trend)}")
m3.metric("Nominal DXY (AFE)", f"{latest_dxy:.2f}", f"{current_dxy_trend*100:.2f}% {arrow(current_dxy_trend)}")
m4.metric("HY Credit Spread", f"{latest_credit:.2f}%", f"{current_credit_trend*100:.0f} bps {arrow(current_credit_trend)}")

st.subheader("System State Machine")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Regime Class", regime)
s2.metric("Credit Condition", credit_status)
s3.metric("System Phase", system_phase)
s4.metric("Liquidity Acceleration", f"{current_liq_accel*100:.2f}% {arrow(current_liq_accel)}")

st.subheader("Execution Vectors")
e1, e2 = st.columns(2)
e1.metric("Dynamic DCA Mode", dca_mode)
e2.metric("Gradient Risk Status", risk_status)
