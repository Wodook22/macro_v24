# engine/strategy.py — 3-슬리브 바벨 전략 (모멘텀 추종의 후행성·하락장 리스크 해결)
#
# 문제: 기존 score_assets는 RS_1m(30%)+RS_3m(20%)=모멘텀 50% → 이미 오른 걸 후행 추종.
#       상승장엔 늦게 진입(SPY 추종만), 하락장엔 꺾인 모멘텀을 늦게 들고 있어 더 깨짐.
#
# 해결: RRG 4사분면으로 자산을 3개 슬리브로 나눠 바벨 구성.
#   1) 선행(Leading-edge) 슬리브  — RRG '개선' 사분면: 아직 안 올랐지만 모멘텀이 돌아서는 중
#                                    → 유동성 유입 '초입' 진입 = SPY 초과수익 원천
#   2) 모멘텀(Momentum) 슬리브     — RRG '주도' 사분면: 이미 강한 추세, 단 '약화' 진입 시 축소
#   3) 방어 앵커(Defensive) 슬리브 — 레짐 연동 동적 비중: Risk-Off일수록 확대(하락장 방어)
#
# 추가 스코어 축:
#   - mean_reversion: 장기추세(200MA) 위 + 단기 과매도(RSI/낙폭) → '곧 오를' 저평가 포착
#   - trend_quality : 모멘텀 높아도 200MA 아래거나 변동성 과도하면 감점 → 모멘텀 함정 회피
import numpy as np
import pandas as pd

from engine.flows import rrg_coords, quadrant


# ─────────────────────────────────────────────────────────────
# 보조 지표
def rsi(close: pd.Series, period: int = 14) -> float:
    d = close.diff().dropna()
    if len(d) < period + 1:
        return 50.0
    up = d.clip(lower=0).rolling(period).mean().iloc[-1]
    dn = (-d.clip(upper=0)).rolling(period).mean().iloc[-1]
    if dn == 0:
        return 100.0
    rs = up / dn
    return float(100 - 100 / (1 + rs))


def mean_reversion_score(close: pd.Series) -> float:
    """장기 우상향(200MA 위)인데 단기 과매도 → 양수(매수 매력).
    장기 하락추세면 과매도여도 0 (밸류 함정 배제)."""
    s = close.dropna()
    if len(s) < 200:
        return 0.0
    ma200 = s.rolling(200).mean().iloc[-1]
    price = s.iloc[-1]
    long_up = price > ma200                       # 장기 추세 우상향 여부
    if not long_up:
        return 0.0
    r = rsi(s)
    # RSI 30 이하 강한 과매도 → +1.0, 50 이상 → 0
    rsi_score = max(0.0, (50 - r) / 20.0)
    # 200MA 대비 단기 이격(아래로 눌릴수록 가점, 단 -15% 이상 깨지면 추세 의심 → 감쇠)
    gap = price / ma200 - 1
    dip_score = 0.0
    if -0.12 < gap < 0.03:
        dip_score = (0.03 - gap) / 0.15           # 살짝 눌린 구간에서 최대
    return float(np.clip(rsi_score + dip_score, 0, 1.5))


def trend_quality_score(close: pd.Series) -> float:
    """추세 '품질'. 200MA 위 + 변동성 적정 + 낙폭 작음 → 양수.
    200MA 아래(하락추세)면 음수 → 모멘텀 높아도 감점(함정 회피)."""
    s = close.dropna()
    if len(s) < 200:
        return 0.0
    price = s.iloc[-1]
    ma50 = s.rolling(50).mean().iloc[-1]
    ma200 = s.rolling(200).mean().iloc[-1]
    rets = s.pct_change().dropna()
    vol = rets.tail(63).std() * np.sqrt(252)
    dd = price / s.tail(126).max() - 1

    score = 0.0
    score += 0.5 if price > ma200 else -0.8       # 장기 추세 위/아래
    score += 0.3 if ma50 > ma200 else -0.3        # 골든/데드 크로스
    if vol > 0.45:                                # 과도한 변동성 = 불안정
        score -= 0.4
    if dd < -0.15:                                # 최근 6M 고점 대비 15%+ 하락
        score -= 0.3
    return float(np.clip(score, -1.5, 1.0))


# ─────────────────────────────────────────────────────────────
# 슬리브 분류
def classify_sleeves(close: pd.DataFrame, bench: str = "SPY",
                     lookback: int = 126, mom: int = 21) -> pd.DataFrame:
    """각 자산을 RRG 사분면 + 보조점수로 분류.
    반환: index=자산, cols=[rs, mom, quadrant, sleeve, mr_score, tq_score]"""
    coords = rrg_coords(close, bench, lookback=lookback, mom=mom)
    rows = {}
    for a, df in coords.items():
        last = df.iloc[-1]
        q = quadrant(float(last["rs"]), float(last["mom"]))
        if q == "개선(Improving)":
            sleeve = "선행"
        elif q == "주도(Leading)":
            sleeve = "모멘텀"
        elif q == "약화(Weakening)":
            sleeve = "차익실현"            # 보유 시 축소 대상
        else:
            sleeve = "회피"               # 침체
        rows[a] = {
            "rs": round(float(last["rs"]), 1),
            "mom": round(float(last["mom"]), 1),
            "quadrant": q, "sleeve": sleeve,
            "mr_score": round(mean_reversion_score(close[a]), 2),
            "tq_score": round(trend_quality_score(close[a]), 2),
        }
    if not rows:
        return pd.DataFrame(columns=["rs", "mom", "quadrant", "sleeve",
                                     "mr_score", "tq_score"])
    return pd.DataFrame(rows).T


# ─────────────────────────────────────────────────────────────
# 방어 앵커 동적 비중 (레짐 연동) — 하락장 리스크의 핵심 제어
def defensive_weight(regime_label: str, vix: float | None,
                     liq_state: str, geo_score: int = 50,
                     crash_1m: int | None = None) -> float:
    """방어 슬리브 목표 비중 (0.12~0.60).
    Risk-Off·고VIX·유동성수축·지정학↑·폭락리스크↑일수록 확대 → 하락장 방어.
    Risk-On 강세장에선 축소해 상승 참여."""
    w = 0.28                                      # 중립 기준
    if regime_label == "Risk-Off":
        w += 0.18
    elif regime_label == "Risk-On":
        w -= 0.16
    if vix is not None:
        if vix >= 30:
            w += 0.13
        elif vix >= 25:
            w += 0.08
        elif vix < 15:
            w -= 0.07
    if liq_state == "Contracting":
        w += 0.08
    elif liq_state == "Expanding":
        w -= 0.06
    if geo_score >= 65:
        w += 0.05
    # 1달 폭락 리스크 게이지(0~100) 연동 — 신용·유동성 경색이 핵심이라 1달 축 사용
    if crash_1m is not None:
        if crash_1m >= 67:
            w += 0.12
        elif crash_1m >= 34:
            w += 0.05
    return float(np.clip(w, 0.12, 0.60))


# ─────────────────────────────────────────────────────────────
# 3-슬리브 자산 선택
DEFENSIVE_TICKERS = ["TLT", "IEF", "GLD", "XLP", "XLU", "XLV", "SHY"]


def build_barbell(close: pd.DataFrame, sleeves: pd.DataFrame,
                  regime_label: str, vix: float | None, liq_state: str,
                  geo_score: int = 50, top_each: int = 3,
                  bench: str = "SPY", crash_1m: int | None = None) -> dict:
    """3-슬리브 바벨 타깃 비중 산출.
    반환: {weights: {ticker: w}, sleeve_alloc: {...}, picks: {...}, def_w: float}"""
    def_w = defensive_weight(regime_label, vix, liq_state, geo_score, crash_1m)
    growth_w = 1.0 - def_w                        # 선행+모멘텀이 나눠가짐

    # 선행/모멘텀 슬리브 내부 비중: 성장 예산을 절반씩, 단 레짐 따라 기울임
    if regime_label == "Risk-On":
        lead_share, mom_share = 0.40, 0.60        # 강세장엔 모멘텀 비중↑
    elif regime_label == "Risk-Off":
        lead_share, mom_share = 0.65, 0.35        # 약세장엔 선행(저평가)↑
    else:
        lead_share, mom_share = 0.50, 0.50

    lead = sleeves[sleeves["sleeve"] == "선행"].copy()
    momo = sleeves[sleeves["sleeve"] == "모멘텀"].copy()

    # 선행: mean-reversion + 모멘텀 회복(mom) 우선
    if not lead.empty:
        lead["rank"] = lead["mr_score"].astype(float) + (lead["mom"].astype(float) - 100) / 50
        lead = lead.sort_values("rank", ascending=False).head(top_each)
    # 모멘텀: 추세품질로 필터 (tq<0 = 200MA 아래 함정 → 제외)
    if not momo.empty:
        momo = momo[momo["tq_score"].astype(float) > -0.3]
        momo["rank"] = momo["rs"].astype(float) + momo["tq_score"].astype(float) * 20
        momo = momo.sort_values("rank", ascending=False).head(top_each)

    weights = {}
    lead_pool = growth_w * lead_share
    mom_pool = growth_w * mom_share
    lead_used = mom_used = 0.0

    # 선행 슬리브 — 후보 없으면 모멘텀으로 이전 (방어 과다 회수 방지)
    if not lead.empty:
        per = lead_pool / len(lead)
        for a in lead.index:
            weights[a] = weights.get(a, 0) + per
        lead_used = lead_pool
    else:
        mom_pool += lead_pool          # 선행 예산 → 모멘텀으로 이전

    # 모멘텀 슬리브 — 후보 없으면 방어로 이전
    if not momo.empty:
        per = mom_pool / len(momo)
        for a in momo.index:
            weights[a] = weights.get(a, 0) + per
        mom_used = mom_pool
    else:
        def_w = min(def_w + mom_pool, 0.75)   # 방어 상한 75% 유지

    # 방어 앵커 배분
    def_avail = [t for t in DEFENSIVE_TICKERS if t in close.columns]
    if def_avail:
        per = def_w / len(def_avail)
        for a in def_avail:
            weights[a] = weights.get(a, 0) + per
    else:
        weights["CASH"] = weights.get("CASH", 0) + def_w

    # 정규화
    tot = sum(weights.values())
    if tot > 0:
        weights = {k: round(v / tot, 4) for k, v in weights.items()}

    return {
        "weights": weights,
        "def_w": round(def_w, 4),
        "sleeve_alloc": {"선행": round(lead_used, 3), "모멘텀": round(mom_used, 3),
                         "방어": round(def_w, 3)},
        "picks": {"선행": list(lead.index), "모멘텀": list(momo.index),
                  "방어": def_avail},
        "tilt": {"lead_share": lead_share, "mom_share": mom_share},
    }
