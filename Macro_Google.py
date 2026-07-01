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

# FREQUENCY FIX: WALCL (Fed balance sheet) only publishes once a week
# (Wednesdays). RRP and TGA publish daily. Previously all three were
# forward-filled onto a shared daily index -- which repeats the same
# single weekly WALCL print across 6 daily rows, creating the illusion of
# daily-resolution granularity in net_liquidity that the underlying data
# doesn't actually support (pct_change(30) would look smoother than the
# real weekly data justifies). Liquidity is a balance-sheet signal, not a
# tick-by-tick one, so we resample all three components down to weekly
# (Wednesday-anchored, matching WALCL's native cadence) before combining.
if not fed.empty:
    fed_w = fed.resample("W-WED").last()
else:
    fed_w = fed
rrp_w = rrp_millions.resample("W-WED").last() if not rrp_millions.empty else rrp_millions
tga_w = tga.resample("W-WED").last() if not tga.empty else tga

df_liq = pd.concat([fed_w, rrp_w, tga_w], axis=1)
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
net_liquidity = df_liq["fed"] - df_liq["rrp"] - df_liq["tga"]  # all in $M now, weekly cadence

# WINDOW FIX: net_liquidity is now weekly (see resample above), so a
# 30-period pct_change would mean 30 WEEKS (~7 months), not 30 days as
# before. To keep the "~1 month lookback" intent from the daily version,
# use 4 weekly periods (~1 month) with a 2-week smoothing window instead
# of the daily 30/5 pairing.
LIQ_WINDOW_WEEKS = 4
LIQ_SMOOTH_WEEKS = 2

liq_impulse_raw = net_liquidity.pct_change(LIQ_WINDOW_WEEKS)
liq_impulse = liq_impulse_raw.rolling(LIQ_SMOOTH_WEEKS).mean().dropna()

liq_trend = liq_impulse.iloc[-1] if not liq_impulse.empty else 0

# ACCELERATION (2nd derivative): is the liquidity trend itself speeding up
# or rolling over? A negative liq_trend that's decelerating (accel > 0)
# suggests contraction may be bottoming; a positive liq_trend that's
# decelerating (accel < 0) suggests expansion may be running out of steam.
# This is a genuinely useful addition on top of first-derivative trend.
liq_acceleration = liq_impulse.diff().iloc[-1] if len(liq_impulse) > 1 else 0

def liq_momentum_state(trend_val, accel_val):
    if trend_val > 0 and accel_val > 0:
        return "EXPANDING (accelerating)"
    elif trend_val > 0 and accel_val <= 0:
        return "EXPANDING (losing steam)"
    elif trend_val <= 0 and accel_val > 0:
        return "CONTRACTING (bottoming)"
    else:
        return "CONTRACTING (accelerating)"

liq_momentum = liq_momentum_state(liq_trend, liq_acceleration)

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
# GAP FIX: previously this only modeled downside/stress states (FRACTURE,
# SYSTEM BREAK) and collapsed every other combination -- including genuine
# liquidity expansion, dollar-weakening easing cycles, and unstable
# "liquidity up but dollar also up" setups -- into a single flat "NORMAL".
# That throws away information you're already computing (liq_trend,
# dxy_trend) elsewhere. Add explicit upside/transitional states so the
# phase output actually reflects the full state space, not just the
# crisis corner of it.
def detect_system_phase(liq, dxy, credit):

    # --- downside / stress states (checked first, highest priority) ---
    if liq < 0 and dxy > 0 and credit == "STRESS SPIKE":
        return "SYSTEM BREAK"

    if liq < 0 and dxy > 0 and credit == "WIDENING":
        return "FRACTURE"

    if credit == "STRESS SPIKE":
        # Credit stress firing even without the liq/dxy alignment above is
        # still worth flagging on its own -- credit markets often lead.
        return "CREDIT STRESS"

    # --- upside / expansion states ---
    if liq > 0 and dxy < 0 and credit == "STABLE":
        # Textbook easing: liquidity rising, dollar weakening, credit calm.
        return "LIQUIDITY EXPANSION"

    if liq > 0 and dxy < 0 and credit == "WIDENING":
        # Liquidity/dollar say expansion, credit hasn't confirmed yet.
        return "EXPANSION (credit lagging)"

    if liq > 0 and dxy > 0:
        # Liquidity rising AND dollar rising is not the clean easing setup
        # -- often reflects safe-haven flows offsetting stimulus, or a
        # short-covering rally rather than durable expansion. Flag as
        # fragile rather than lumping it in with NORMAL or true expansion.
        return "FRAGILE EXPANSION"

    return "NORMAL"

system_phase = detect_system_phase(liq_trend, dxy_trend, credit_status)

# --------------------------------------------------
# REGIME
# --------------------------------------------------
# MAGNITUDE FIX: previously any nonzero sign (even a +0.0001% noise move)
# was enough to trigger a full regime label like "QT" or "HARD_PIVOT".
# That treats a rounding-error-sized move the same as a real repricing.
# Add a minimum-magnitude threshold both signals must clear before a
# directional regime is assigned; sub-threshold moves fall through to
# TRANSITION (i.e. "no clear signal yet") instead of a false-confidence
# label.
REGIME_MAGNITUDE_THRESHOLD = 0.02  # 2% minimum move to count as directional

def classify_regime(y, d, threshold=REGIME_MAGNITUDE_THRESHOLD):
    y_sig = y if abs(y) >= threshold else 0
    d_sig = d if abs(d) >= threshold else 0

    if y_sig > 0 and d_sig > 0:
        return "QT"
    elif y_sig < 0 and d_sig < 0:
        return "SOFT_PIVOT"
    elif y_sig < 0 and d_sig > 0:
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
# GAP FIX: previously these were hardcoded absolute thresholds
# (liq_trend > 0.05 / > 0) with no relationship to what's actually normal
# for this series historically. A 5% liquidity swing might be enormous in
# a calm regime or unremarkable in a volatile one -- the threshold doesn't
# adapt. Instead, rank the current liq_trend against its own full history
# (percentile) so "HIGH DCA" means "liquidity impulse is genuinely strong
# relative to its own past," not an arbitrary fixed number.
def compute_dca_mode(current_trend, trend_history, min_history=10):
    if trend_history is None or len(trend_history.dropna()) < min_history:
        # Not enough history to rank against -- default to caution rather
        # than a possibly-misleading confident label.
        return "LOW / PAUSE (insufficient history)"

    hist = trend_history.dropna()
    percentile = (hist < current_trend).mean()  # fraction of history below current value

    if percentile >= 0.70:
        return "HIGH DCA"
    elif percentile >= 0.40:
        return "MEDIUM DCA"
    else:
        return "LOW / PAUSE"

dca_mode = compute_dca_mode(liq_trend, liq_impulse)

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

c5, c6, c7, c8 = st.columns(4)
c5.metric("Regime", regime)
c6.metric("Credit Condition", credit_status)
c7.metric("System Phase", system_phase)
c8.metric("Liquidity Momentum", liq_momentum,
          f"accel: {liq_acceleration*100:.2f}%")

# --------------------------------------------------
# EXECUTION
# --------------------------------------------------
st.subheader("Execution")

col1, col2 = st.columns(2)
col1.metric("DCA Mode", dca_mode)
# CONSISTENCY FIX: system_phase now has multiple stress states
# (SYSTEM BREAK, FRACTURE, CREDIT STRESS), but this previously only
# checked for SYSTEM BREAK -- so a FRACTURE or CREDIT STRESS reading
# would silently still show "ACTIVE". Flag all stress-family states.
STRESS_PHASES = {"SYSTEM BREAK", "FRACTURE", "CREDIT STRESS"}
col2.metric("Risk Status", "RISK OFF" if system_phase in STRESS_PHASES else "ACTIVE")
