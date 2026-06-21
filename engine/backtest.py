# engine/backtest.py — 섹터 로테이션 백테스트 (§1-4 수정)
# 핵심: engine/scoring.score_assets와 "같은 함수" 사용 (가격 5축).
# 룩어헤드 방지: t월말까지 데이터로 스코어 → t+1월 첫 거래일부터 보유
import numpy as np
import pandas as pd

from core.utils import perf_stats
from engine.scoring import score_assets, PRICE_AXES


def run_backtest(close: pd.DataFrame, start: str, top_n: int = 3,
                 bench: str = "SPY", cost_bps: float = 5.0,
                 weights: dict | None = None) -> dict | None:
    close = close.dropna(how="all").loc[start:]
    if close.empty or bench not in close.columns:
        return None
    # 스코어 계산엔 룩백(최대 200일)이 필요하므로 전체 close를 받고 시작일 이전 데이터도 활용
    rebal_dates = close.resample("ME").last().index
    rebal_dates = [d for d in rebal_dates if d >= pd.Timestamp(start)]
    if len(rebal_dates) < 6:
        return None

    daily = close.pct_change()
    port_ret = pd.Series(0.0, index=close.index)
    prev_w: dict = {}
    holdings_log = []

    for i, t in enumerate(rebal_dates[:-1]):
        hist = close.loc[:t]                          # ← t 시점까지의 데이터만
        if len(hist) < 130:
            continue
        scored = score_assets(hist, volume=None, weights=weights, bench=bench)
        scored = scored[[c for c in scored.columns if c in PRICE_AXES + ["score"]]]
        picks = list(scored.head(top_n).index)
        new_w = {p: 1.0 / top_n for p in picks}

        nxt = rebal_dates[i + 1]
        period = daily.loc[t:nxt].iloc[1:]            # t 다음 거래일부터
        if period.empty:
            continue
        r = period[picks].mean(axis=1)

        turnover = sum(abs(new_w.get(a, 0) - prev_w.get(a, 0))
                       for a in set(new_w) | set(prev_w))
        cost = turnover * cost_bps / 10000.0
        if len(r):
            r.iloc[0] -= cost                         # 리밸런싱 직후 첫 거래일 차감
        port_ret.loc[r.index] = r
        prev_w = new_w
        holdings_log.append({"date": t.date(), "보유": ", ".join(picks),
                             "비용(bp)": round(turnover * cost_bps, 1)})

    port_ret = port_ret.loc[rebal_dates[0]:]
    eq = (1 + port_ret).cumprod()
    bench_eq = (1 + daily[bench].loc[eq.index].fillna(0)).cumprod()
    return {
        "equity": eq, "bench_equity": bench_eq,
        "stats": perf_stats(eq), "bench_stats": perf_stats(bench_eq),
        "holdings": pd.DataFrame(holdings_log),
        "note": ("⚠️ 백테스트는 가격 기반 5축(RS1M/RS3M/추세/저변동/낙폭)만 검증합니다. "
                 "거래량·레짐적합·밸류에이션 축은 과거 시점 재구성이 어려워 제외 — "
                 "실거래 스코어와 동일 함수를 사용하되 축이 줄어든 버전임을 유의하세요. "
                 "종목(개별주) 백테스트는 생존편향 때문에 제공하지 않습니다."),
    }


# ─────────────────────────────────────────────────────────────
# 3-슬리브 바벨 전략 백테스트 (engine/strategy.py 사용)
def _price_regime(spy_hist: pd.Series, vix_hist: pd.Series | None) -> tuple[str, float | None, str]:
    """과거 각 시점에서 룩어헤드 없이 계산하는 가격 기반 레짐 프록시.
    (실거래는 7축 매크로 레짐을 쓰지만, 백테스트는 과거 매크로 재구성이 어려워 가격 프록시 사용)"""
    s = spy_hist.dropna()
    if len(s) < 200:
        return "Mixed", None, "Neutral"
    price = s.iloc[-1]
    ma200 = s.rolling(200).mean().iloc[-1]
    ma50 = s.rolling(50).mean().iloc[-1]
    vix = None
    if vix_hist is not None and len(vix_hist.dropna()):
        vix = float(vix_hist.dropna().iloc[-1])

    above = price > ma200
    rising = ma50 > ma200
    if above and rising and (vix is None or vix < 22):
        label = "Risk-On"
    elif (not above) or (vix is not None and vix >= 28):
        label = "Risk-Off"
    else:
        label = "Mixed"
    # 유동성 프록시: SPY 50MA 기울기
    liq = "Neutral"
    if len(s) > 70:
        slope = ma50 / s.rolling(50).mean().iloc[-21] - 1
        liq = "Expanding" if slope > 0.01 else ("Contracting" if slope < -0.01 else "Neutral")
    return label, vix, liq


def run_barbell_backtest(close: pd.DataFrame, start: str, bench: str = "SPY",
                         cost_bps: float = 5.0, top_each: int = 3) -> dict | None:
    """3-슬리브 바벨 백테스트. 매월 RRG 사분면으로 슬리브 분류 → 동적 비중.
    레짐은 가격 프록시(SPY 200MA + VIX)로 룩어헤드 없이 재구성."""
    from engine.strategy import classify_sleeves, build_barbell

    close = close.dropna(how="all")
    if close.empty or bench not in close.columns:
        return None
    rebal_dates = close.resample("ME").last().index
    rebal_dates = [d for d in rebal_dates if d >= pd.Timestamp(start)]
    if len(rebal_dates) < 6:
        return None

    daily = close.pct_change()
    port_ret = pd.Series(0.0, index=close.index)
    prev_w: dict = {}
    holdings_log = []
    vix_col = "^VIX" if "^VIX" in close.columns else None

    for i, t in enumerate(rebal_dates[:-1]):
        hist = close.loc[:t]
        if len(hist) < 210:                          # 200MA + 여유
            continue
        label, vix, liq = _price_regime(
            hist[bench], hist[vix_col] if vix_col else None)
        sleeves = classify_sleeves(hist.drop(columns=[vix_col] if vix_col else []),
                                   bench=bench)
        if sleeves.empty:
            continue
        bar = build_barbell(hist, sleeves, label, vix, liq,
                            geo_score=50, top_each=top_each, bench=bench)
        new_w = {k: v for k, v in bar["weights"].items() if k != "CASH"}
        cash_w = bar["weights"].get("CASH", 0.0)
        if not new_w:
            continue

        nxt = rebal_dates[i + 1]
        period = daily.loc[t:nxt].iloc[1:]
        if period.empty:
            continue
        cols = [a for a in new_w if a in period.columns]
        wv = pd.Series({a: new_w[a] for a in cols})
        wv = wv / (wv.sum() + cash_w) if (wv.sum() + cash_w) > 0 else wv
        r = (period[cols] * wv).sum(axis=1)          # 현금은 0% 수익

        turnover = sum(abs(new_w.get(a, 0) - prev_w.get(a, 0))
                       for a in set(new_w) | set(prev_w))
        cost = turnover * cost_bps / 10000.0
        if len(r):
            r.iloc[0] -= cost
        port_ret.loc[r.index] = r
        prev_w = new_w
        holdings_log.append({
            "date": t.date(), "레짐": label,
            "방어%": round(bar["def_w"] * 100),
            "선행": ", ".join(bar["picks"]["선행"][:3]) or "—",
            "모멘텀": ", ".join(bar["picks"]["모멘텀"][:3]) or "—",
            "비용(bp)": round(turnover * cost_bps, 1)})

    port_ret = port_ret.loc[rebal_dates[0]:]
    eq = (1 + port_ret).cumprod()
    bench_eq = (1 + daily[bench].loc[eq.index].fillna(0)).cumprod()
    return {
        "equity": eq, "bench_equity": bench_eq,
        "stats": perf_stats(eq), "bench_stats": perf_stats(bench_eq),
        "holdings": pd.DataFrame(holdings_log),
        "note": ("3-슬리브 바벨: RRG 사분면으로 선행(개선)·모멘텀(주도)·방어 슬리브 구성. "
                 "방어 비중은 가격 레짐 프록시(SPY 200MA + VIX)로 동적 조절. "
                 "⚠️ 실거래는 7축 매크로 레짐을 쓰지만 백테스트는 과거 매크로 재구성이 "
                 "어려워 가격 프록시로 근사 — 실제 성과와 차이날 수 있음. ETF만 검증(생존편향 회피)."),
    }
