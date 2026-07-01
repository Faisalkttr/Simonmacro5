import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Sovereign Macro Engine", layout="wide", page_icon="🛡️")

# --------------------------------------------------
# THEME / CSS
# --------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }

.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1200px; }

/* Streamlit default title/caption restyle */
h1 { font-weight: 800 !important; letter-spacing: -0.02em; }

.sme-section-label {
    font-size: 12px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
    color: #8892a6; margin: 28px 0 10px 0; display: flex; align-items: center; gap: 8px;
}
.sme-section-label::after {
    content: ""; flex: 1; height: 1px; background: #232838; margin-left: 8px;
}

.sme-asof {
    display:inline-block; font-size:12px; color:#8892a6; background:#12161f;
    border:1px solid #232838; border-radius:999px; padding:4px 12px; margin-bottom:6px;
}

.sme-card {
    background: #12161f; border: 1px solid #232838; border-left: 4px solid var(--accent, #7fa8c9);
    border-radius: 12px; padding: 16px 18px; height: 100%;
}
.sme-card .lbl {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #8892a6;
}
.sme-card .val {
    font-family: 'JetBrains Mono', monospace; font-size: 26px; font-weight: 700; color: #eef1f7; margin: 6px 0 2px 0;
}
.sme-card .delta { font-size: 13px; font-weight: 600; color: var(--accent, #7fa8c9); }
.sme-card .note { font-size: 11px; color: #6b7385; margin-top: 4px; }

.sme-badge {
    background: var(--bg, #12161f); border: 1px solid var(--accent, #7fa8c9); border-radius: 12px;
    padding: 16px 18px; text-align: center; height: 100%;
}
.sme-badge .lbl {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #8892a6;
}
.sme-badge .val {
    font-size: 19px; font-weight: 800; color: var(--accent, #7fa8c9); margin-top: 8px;
}
.sme-badge .note { font-size: 11px; color: #6b7385; margin-top: 6px; }

.sme-hero {
    border-radius: 16px; padding: 24px 28px; margin: 4px 0 26px 0;
    background: var(--bg, #12161f); border: 1px solid var(--accent, #7fa8c9);
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;
}
.sme-hero .tag {
    font-size: 12px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #8892a6;
}
.sme-hero .phase {
    font-size: 30px; font-weight: 800; color: var(--accent, #7fa8c9); margin-top: 4px;
}
.sme-hero .side { text-align: right; font-size: 13px; color: #8892a6; line-height: 1.7; }
.sme-hero .side b { color: #eef1f7; }
</style>
""", unsafe_allow_html=True)

st.title("🛡️ Sovereign Macro Execution Engine")
st.caption("Execution > Prediction  |  Survival First")

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
# STYLE MAPS (map computed states -> color/icon, purely presentational)
# --------------------------------------------------
PHASE_STYLE = {
    "SYSTEM BREAK":              {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)",  "icon": "🚨"},
    "FRACTURE":                  {"accent": "#ff8c42", "bg": "rgba(255,140,66,0.08)", "icon": "⚠️"},
    "CREDIT STRESS":             {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.08)", "icon": "⚠️"},
    "FRAGILE EXPANSION":         {"accent": "#e8d44d", "bg": "rgba(232,212,77,0.08)", "icon": "🌀"},
    "EXPANSION (credit lagging)":{"accent": "#8de07a", "bg": "rgba(141,224,122,0.08)","icon": "📈"},
    "LIQUIDITY EXPANSION":       {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.08)", "icon": "✅"},
    "NORMAL":                    {"accent": "#7fa8c9", "bg": "rgba(127,168,201,0.08)","icon": "➖"},
}
REGIME_STYLE = {
    "QT":           {"accent": "#ff8c42", "bg": "rgba(255,140,66,0.06)", "icon": "🔻"},
    "SOFT_PIVOT":   {"accent": "#8de07a", "bg": "rgba(141,224,122,0.06)","icon": "🌤️"},
    "HARD_PIVOT":   {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)", "icon": "⚡"},
    "EARLY_PIVOT":  {"accent": "#4dd6c9", "bg": "rgba(77,214,201,0.06)", "icon": "🔔"},
    "TRANSITION":   {"accent": "#9aa5b1", "bg": "rgba(154,165,177,0.06)","icon": "↔️"},
}
CREDIT_STYLE = {
    "STRESS SPIKE": {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.06)", "icon": "🔴"},
    "WIDENING":     {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)","icon": "🟠"},
    "STABLE":       {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)","icon": "🟢"},
}
DCA_STYLE = {
    "HIGH DCA":                          {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.06)"},
    "MEDIUM DCA":                        {"accent": "#ffb84d", "bg": "rgba(255,184,77,0.06)"},
    "LOW / PAUSE":                       {"accent": "#9aa5b1", "bg": "rgba(154,165,177,0.06)"},
    "LOW / PAUSE (insufficient history)":{"accent": "#6b7385", "bg": "rgba(107,115,133,0.06)"},
}
RISK_STYLE = {
    "RISK OFF": {"accent": "#ff4d4d", "bg": "rgba(255,77,77,0.08)"},
    "ACTIVE":   {"accent": "#4dd68c", "bg": "rgba(77,214,140,0.08)"},
}

def get_style(mapping, key, default_accent="#7fa8c9", default_bg="rgba(127,168,201,0.06)"):
    return mapping.get(key, {"accent": default_accent, "bg": default_bg, "icon": ""})

def arrow_html(x, up_color="#4dd68c", down_color="#ff6b6b", flat_color="#9aa5b1"):
    if x > 0:
        return f'<span style="color:{up_color};">▲</span>'
    elif x < 0:
        return f'<span style="color:{down_color};">▼</span>'
    return f'<span style="color:{flat_color};">→</span>'

def metric_card(label, value, delta_pct, note="", icon=""):
    accent = "#4dd68c" if delta_pct > 0 else ("#ff6b6b" if delta_pct < 0 else "#9aa5b1")
    arrow = arrow_html(delta_pct)
    html = f"""
    <div class="sme-card" style="--accent:{accent};">
        <div class="lbl">{icon} {label}</div>
        <div class="val">{value}</div>
        <div class="delta">{delta_pct*100:+.2f}% {arrow}</div>
        {f'<div class="note">{note}</div>' if note else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def badge_card(label, value, style, note=""):
    html = f"""
    <div class="sme-badge" style="--accent:{style['accent']}; --bg:{style['bg']}; background:{style['bg']};">
        <div class="lbl">{label}</div>
        <div class="val">{style.get('icon','')} {value}</div>
        {f'<div class="note">{note}</div>' if note else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
if as_of_date is not None:
    st.markdown(f'<div class="sme-asof">📅 Data as of {as_of_date.strftime("%Y-%m-%d")} '
                f'(forward-filled to common calendar)</div>', unsafe_allow_html=True)

# --- HERO: the one thing you should see first ---
phase_style = get_style(PHASE_STYLE, system_phase)
st.markdown(f"""
<div class="sme-hero" style="--accent:{phase_style['accent']}; background:{phase_style['bg']};">
    <div>
        <div class="tag">Current System Phase</div>
        <div class="phase">{phase_style['icon']} {system_phase}</div>
    </div>
    <div class="side">
        Regime &nbsp;<b>{REGIME_STYLE.get(regime,{}).get('icon','')} {regime}</b><br/>
        DCA Mode &nbsp;<b>{dca_mode}</b><br/>
        Liquidity Momentum &nbsp;<b>{liq_momentum}</b>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="sme-section-label">📊 Macro Chokepoints</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    metric_card("Liquidity", format_liquidity(latest_liquidity), liq_trend, icon="💧")
with c2:
    metric_card("10Y Yield", f"{latest_yield:.2f}%", yield_trend, icon="📉")
with c3:
    metric_card("USD Index (Fed Broad-AFE)", f"{latest_usd_broad:.2f}", dxy_trend, icon="💵",
                note="Fed's Nominal Advanced Foreign Economies index — NOT the ICE DXY quote. Levels aren't comparable; trend direction is.")
with c4:
    metric_card("Credit Spread", f"{latest_credit:.2f}%", credit_trend_val, icon="🏦")

st.markdown('<div class="sme-section-label">🧭 System State</div>', unsafe_allow_html=True)

c5, c6, c7, c8 = st.columns(4)
with c5:
    badge_card("Regime", regime, get_style(REGIME_STYLE, regime))
with c6:
    badge_card("Credit Condition", credit_status, get_style(CREDIT_STYLE, credit_status))
with c7:
    badge_card("System Phase", system_phase, phase_style)
with c8:
    badge_card("Liquidity Momentum", liq_momentum,
                {"accent": "#4dd68c" if liq_acceleration > 0 else "#ff6b6b", "bg": "rgba(127,168,201,0.06)"},
                note=f"acceleration: {liq_acceleration*100:+.2f}%")

st.markdown('<div class="sme-section-label">⚙️ Execution</div>', unsafe_allow_html=True)

STRESS_PHASES = {"SYSTEM BREAK", "FRACTURE", "CREDIT STRESS"}
risk_status = "RISK OFF" if system_phase in STRESS_PHASES else "ACTIVE"

col1, col2 = st.columns(2)
with col1:
    badge_card("DCA Mode", dca_mode, get_style(DCA_STYLE, dca_mode))
with col2:
    badge_card("Risk Status", risk_status, get_style(RISK_STYLE, risk_status))
