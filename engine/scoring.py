# engine/scoring.py — 자산 스코어링 (§1-1, §1-4)
# 핵심: 백테스트와 실시간이 "같은 함수"를 호출. 시점 t 데이터만 받음 (룩어헤드 방지)
import numpy as np
import pandas as pd

from core.config import DEFAULT_SCORE_W, AGGRESSIVE, DEFENSIVE, pe_penalty
from core.utils import xsec_z, ann_vol, current_drawdown

PRICE_AXES = ["rs_1m", "rs_3m", "trend", "low_vol", "drawdown"]  # 가격만으로 계산 가능
LIVE_AXES = PRICE_AXES + ["volume", "macro_fit", "valuation"]


def normalize_weights(w: dict, axes: list[str]) -> dict:
    """가용 축만 남기고 합=1.00 자동 정규화 (§1-1 — 합 경고 기능 자체가 불필요해짐)"""
    sub = {k: v for k, v in w.items() if k in axes and v > 0}
    tot = sum(sub.values())
    return {k: v / tot for k, v in sub.items()} if tot else {}


def metric_table(close: pd.DataFrame, volume: pd.DataFrame | None = None,
                 bench: str = "SPY") -> pd.DataFrame:
    """close 마지막 행 시점의 원시 지표 (시점 t까지의 데이터만 사용)"""
    close = close.dropna(how="all")
    assets = [c for c in close.columns if c != bench]
    if close.empty or not assets or len(close) < 64:   # 최소 3M 룩백 미달
        return pd.DataFrame()
    rets = close.pct_change()
    out = pd.DataFrame(index=assets)

    b1 = close[bench].pct_change(21).iloc[-1] if bench in close else 0.0
    b3 = close[bench].pct_change(63).iloc[-1] if bench in close else 0.0
    out["rs_1m"] = close[assets].pct_change(21).iloc[-1] - b1
    out["rs_3m"] = close[assets].pct_change(63).iloc[-1] - b3

    ma50 = close[assets].rolling(50).mean()
    ma200 = close[assets].rolling(200).mean()
    golden = (ma50.iloc[-1] > ma200.iloc[-1]).astype(float) * 0.05
    out["trend"] = close[assets].iloc[-1] / ma50.iloc[-1] - 1 + golden

    out["vol_raw"] = pd.Series({a: ann_vol(rets[a]).iloc[-1] for a in assets})
    out["drawdown"] = pd.Series({a: current_drawdown(close[a]).iloc[-1] for a in assets})

    if volume is not None and not volume.empty:
        vcols = [a for a in assets if a in volume.columns]
        if vcols:
            vr = volume[vcols].iloc[-1] / volume[vcols].rolling(20).mean().iloc[-1]
            out["volume"] = vr.reindex(assets)
    return out


def calc_macro_fit(sector_name: str, regime: dict, liq_state: str,
                   vix: float | None, hy_rising: bool,
                   rate_rising: bool, high_infl: bool) -> float:
    """v17.1 §8 규칙 유지"""
    s = 0.0
    label = regime.get("label", "Mixed")
    if label == "Risk-On":
        s += 0.70 if sector_name in AGGRESSIVE else -0.30
    elif label == "Risk-Off":
        s += 0.90 if sector_name in DEFENSIVE else -0.40
    if liq_state == "Expanding" and sector_name in ("Technology", "Communication Services"):
        s += 0.35
    if vix is not None and vix >= 25 and sector_name in DEFENSIVE:
        s += 0.45
    if hy_rising and sector_name in ("Consumer Staples", "Health Care", "Utilities"):
        s += 0.35
    if rate_rising and sector_name in ("Financials", "Energy"):
        s += 0.25
    if high_infl and sector_name in ("Energy", "Materials"):
        s += 0.40
    return s


def score_assets(close: pd.DataFrame, volume: pd.DataFrame | None = None,
                 weights: dict | None = None, macro_fit: dict | None = None,
                 pe: dict | None = None, bench: str = "SPY") -> pd.DataFrame:
    """종합 스코어. 백테스트는 close만 넘김 → 가격 5축으로 자동 축소 + 가중치 재정규화"""
    w = dict(weights or DEFAULT_SCORE_W)
    m = metric_table(close, volume, bench)
    if m.empty:
        return m

    z = pd.DataFrame(index=m.index)
    z["rs_1m"] = xsec_z(m["rs_1m"])
    z["rs_3m"] = xsec_z(m["rs_3m"])
    z["trend"] = xsec_z(m["trend"])
    z["low_vol"] = -xsec_z(m["vol_raw"])              # 낮을수록 가점
    z["drawdown"] = xsec_z(m["drawdown"])             # dd가 0에 가까울수록 가점
    if "volume" in m:
        z["volume"] = xsec_z(m["volume"])
    if macro_fit:
        z["macro_fit"] = pd.Series(macro_fit).reindex(m.index).fillna(0.0)  # 이미 점수 스케일
    if pe:
        z["valuation"] = pd.Series({a: pe_penalty(pe.get(a)) for a in m.index}) * 2  # 스케일 보정
    z = z.clip(-3, 3)

    wn = normalize_weights(w, list(z.columns))
    score = sum(z[k] * v for k, v in wn.items())
    res = z.copy()
    res["score"] = score
    res["_axes_used"] = ",".join(wn.keys())
    return res.sort_values("score", ascending=False)


def reason_table(scored: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """투자 추천 이유표 (v17.1 §20 신규기능 1): 자산별 선택근거/주의사항"""
    rows = []
    for asset, r in scored.head(top_n).iterrows():
        contrib = {k: r[k] for k in r.index
                   if k in LIVE_AXES and isinstance(r[k], (int, float, np.floating))}
        top = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)[:2]
        worst = min(contrib.items(), key=lambda kv: kv[1]) if contrib else ("—", 0)
        name_map = {"rs_1m": "1M 상대강도", "rs_3m": "3M 상대강도", "trend": "추세",
                    "low_vol": "저변동성", "drawdown": "낙폭방어", "volume": "거래량",
                    "macro_fit": "레짐 적합", "valuation": "밸류에이션"}
        rows.append({
            "자산": asset, "종합점수": round(float(r["score"]), 2),
            "선택 이유": " + ".join(f"{name_map.get(k, k)}({v:+.1f})" for k, v in top),
            "주의사항": f"{name_map.get(worst[0], worst[0])} 약함({worst[1]:+.1f})"
                       if worst[1] < -0.3 else "—",
        })
    return pd.DataFrame(rows)
