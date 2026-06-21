# ui/common.py — 페이지 공용 파이프라인
import pandas as pd
import streamlit as st

from core.config import (SECTOR_ETFS, NEWS_CATEGORIES, GLOBAL_INDICES,
                         DEFAULT_SCORE_W)
from core.utils import get_val
from data.fred import build_macro
from data.market import fetch_prices, fetch_etf_pe
from data.news import gdelt_all, gdelt_category_score, total_geo_score
from engine.liquidity import weekly_liquidity, liquidity_state
from engine.regime import classify_axes, regime_summary
from engine.scoring import score_assets, calc_macro_fit


def sidebar_state() -> dict:
    """app.py 사이드바에서 설정한 값들"""
    return {k: st.session_state.get(k) for k in
            ["period", "top_n", "n_stocks", "max_asset", "max_sector",
             "cost_bps", "rf", "geo_override", "anthropic_key", "gemini_key"]}


@st.cache_data(ttl=900, show_spinner="시장 데이터 로드 중...")
def sector_prices(period: str = "2y"):
    tickers = tuple(list(SECTOR_ETFS.values()) + ["SPY", "^VIX"])
    return fetch_prices(tickers, period)


def get_geo() -> tuple[int, str, dict]:
    """지정학 자동 점수. gdelt_all()로 한 번만 호출해 429 방지."""
    override = st.session_state.get("geo_override", "자동")
    all_results = gdelt_all()
    scores = {cat: (r["score"] if r else None) for cat, r in all_results.items()}
    score, label = total_geo_score(scores)
    if override != "자동":
        label = override
        score = {"Low": 30, "Medium": 55, "High": 80}[override]
    return score, label, scores


def get_state() -> dict:
    """레짐 파이프라인: 매크로 → 유동성 → 7축 → 히스테리시스"""
    macro = build_macro()
    wliq = weekly_liquidity(macro)
    liq = liquidity_state(wliq)

    close, _ = sector_prices(st.session_state.get("period", "2y"))
    vix = None
    if "^VIX" in close.columns:
        s = close["^VIX"].dropna()
        vix = float(s.iloc[-1]) if len(s) else None

    axes = classify_axes(macro, vix, liq)
    prev = st.session_state.get("_prev_regime")
    reg = regime_summary(axes, prev)
    # 트리거 비교용 직전 값 보관 후 갱신
    st.session_state["_prev_regime_for_trigger"] = prev
    st.session_state["_prev_regime"] = reg["label"]

    return {"macro": macro, "wliq": wliq, "liq": liq, "vix": vix,
            "regime": reg, "close": close}


def sector_macro_fit(state: dict) -> dict:
    macro, reg, liq, vix = state["macro"], state["regime"], state["liq"], state["vix"]
    hy = get_val(macro, "HY_1M_Chg")
    r10 = get_val(macro, "DGS10_1M_Chg")
    cpi = get_val(macro, "CPI_YoY")
    fit = {}
    for name, etf in SECTOR_ETFS.items():
        fit[etf] = calc_macro_fit(
            name, reg, liq["state"], vix,
            hy_rising=(hy is not None and hy > 0.1),
            rate_rising=(r10 is not None and r10 > 0.2),
            high_infl=(cpi is not None and cpi > 4))
    return fit


def scored_sectors(state: dict, use_pe: bool = True) -> pd.DataFrame:
    close, volume = sector_prices(st.session_state.get("period", "2y"))
    cols = [c for c in close.columns if c != "^VIX"]
    fit = sector_macro_fit(state)
    pe = fetch_etf_pe(tuple(SECTOR_ETFS.values())) if use_pe else None
    w = st.session_state.get("score_weights", DEFAULT_SCORE_W)
    return score_assets(close[cols], volume[cols] if not volume.empty else None,
                        weights=w, macro_fit=fit, pe=pe, bench="SPY")


@st.cache_data(ttl=900, show_spinner=False)
def index_snapshot() -> pd.DataFrame:
    close, _ = fetch_prices(tuple(GLOBAL_INDICES.values()), "6mo")
    rows = []
    for name, t in GLOBAL_INDICES.items():
        if t not in close.columns:
            continue
        s = close[t].dropna()
        if len(s) < 25:
            continue
        rows.append({"지수": name, "현재": round(float(s.iloc[-1]), 1),
                     "1일": s.iloc[-1] / s.iloc[-2] - 1,
                     "1개월": s.iloc[-1] / s.iloc[-21] - 1})
    return pd.DataFrame(rows)
