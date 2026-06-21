# engine/timing.py — 진입 타이밍 / 조정 분할매수 / 폭락장 차단기 (v18.2)
#
# 설계 철학 (원석님 아이디어 + 냉정한 리스크 관리):
#   - "공포에 줍는다"는 강세장 조정엔 강력하지만 약세장 초입엔 '떨어지는 칼날'.
#   - 따라서 '레짐 게이트'가 두 모드를 가른다:
#       (A) 강세장/조정 모드 → 공포+지지선+라운드넘버 '합류' 시 분할매수
#       (B) 폭락장 차단 모드 → 조정매수 전면 중단, 바닥은 장기지지선에서만
#   - 마틴게일 방지: 탄약(자본) 상한 + 회차 제한 필수.
#   - 지지선은 '반등 보장'이 아니라 '깨지면 가설 무효'의 기준으로 사용.
import numpy as np
import pandas as pd

from engine.strategy import rsi


# ─────────────────────────────────────────────────────────────
# 1) 지지/저항 자동 탐지 (스윙 고저점 + 라운드넘버 클러스터)
def find_support_resistance(close: pd.Series, lookback: int = 252,
                            n_levels: int = 4, bin_pct: float = 0.02) -> dict:
    """최근 lookback 일의 스윙 포인트를 가격대로 클러스터링.
    반환: {support: [..], resistance: [..], price: 현재가}"""
    s = close.dropna().tail(lookback)
    if len(s) < 40:
        return {"support": [], "resistance": [], "price": None}
    price = float(s.iloc[-1])

    # 스윙 하이/로우 (좌우 5일 극값)
    win = 5
    highs, lows = [], []
    vals = s.values
    for i in range(win, len(vals) - win):
        seg = vals[i - win:i + win + 1]
        if vals[i] == seg.max():
            highs.append(vals[i])
        if vals[i] == seg.min():
            lows.append(vals[i])

    def cluster(levels):
        """가까운 레벨을 묶어 빈도 가중 대표값 산출"""
        if not levels:
            return []
        levels = sorted(levels)
        clusters, cur = [], [levels[0]]
        for v in levels[1:]:
            if abs(v - cur[-1]) / cur[-1] < bin_pct:
                cur.append(v)
            else:
                clusters.append(cur)
                cur = [v]
        clusters.append(cur)
        # (대표값, 터치횟수) — 터치 많을수록 강한 레벨
        out = [(float(np.mean(c)), len(c)) for c in clusters]
        return sorted(out, key=lambda x: -x[1])

    all_levels = cluster(highs + lows)
    support = sorted([(lv, t) for lv, t in all_levels if lv < price * 0.995],
                     key=lambda x: -x[0])[:n_levels]
    resistance = sorted([(lv, t) for lv, t in all_levels if lv > price * 1.005],
                        key=lambda x: x[0])[:n_levels]

    # 라운드넘버 (심리적 레벨): 가격 자릿수에 맞춘 100/50 단위
    mag = 10 ** (len(str(int(price))) - 2)        # 예: 4500 → 100
    round_levels = []
    for k in range(-3, 4):
        rl = (round(price / mag) + k) * mag
        if rl > 0:
            round_levels.append(rl)

    return {"support": support, "resistance": resistance, "price": price,
            "round_levels": round_levels, "mag": mag}


# ─────────────────────────────────────────────────────────────
# 2) 합류(confluence) 점수 — 여러 신호가 겹치는 가격대가 강하다
def confluence_score(close: pd.Series, fear_greed: float | None,
                     sr: dict | None = None) -> dict:
    """현재가 기준 매수 매력 합류 점수 (0~100) + 근거.
    공포탐욕 + 지지선 근접 + 라운드넘버 + 과매도(RSI) + 단기 낙폭."""
    s = close.dropna()
    if len(s) < 60:
        return {"score": 0, "signals": [], "price": None}
    price = float(s.iloc[-1])
    sr = sr or find_support_resistance(close)
    signals = []
    pts = 0.0

    # 공포탐욕 (가장 큰 가중)
    if fear_greed is not None:
        if fear_greed <= 15:
            pts += 35; signals.append(("극도 공포", f"F&G {fear_greed:.0f}", 35))
        elif fear_greed <= 25:
            pts += 25; signals.append(("공포", f"F&G {fear_greed:.0f}", 25))
        elif fear_greed <= 40:
            pts += 12; signals.append(("약한 공포", f"F&G {fear_greed:.0f}", 12))

    # 지지선 근접 (3% 이내)
    near_sup = None
    for lv, touches in sr.get("support", []):
        dist = (price - lv) / price
        if 0 <= dist < 0.03:
            near_sup = (lv, touches)
            pts += 18 + min(touches * 2, 10)
            signals.append(("지지선 근접", f"{lv:.0f} ({touches}회 터치)",
                            18 + min(touches * 2, 10)))
            break

    # 라운드넘버 근접 (1.5% 이내, 현재가보다 낮은 지지성 레벨만)
    for rl in sorted([r for r in sr.get("round_levels", []) if r < price],
                     reverse=True):
        if abs(price - rl) / price < 0.015:
            pts += 8; signals.append(("라운드넘버", f"{rl:.0f}", 8))
            break

    # RSI 과매도
    r = rsi(s)
    if r < 30:
        pts += 18; signals.append(("RSI 과매도", f"{r:.0f}", 18))
    elif r < 40:
        pts += 8; signals.append(("RSI 눌림", f"{r:.0f}", 8))

    # 단기 낙폭 (고점 대비 5% 이상 조정)
    dd = price / s.tail(60).max() - 1
    if dd < -0.10:
        pts += 14; signals.append(("10%+ 조정", f"{dd*100:.0f}%", 14))
    elif dd < -0.05:
        pts += 8; signals.append(("5%+ 조정", f"{dd*100:.0f}%", 8))

    return {"score": int(min(100, pts)), "signals": signals, "price": price,
            "near_support": near_sup, "sr": sr, "rsi": round(r, 1),
            "drawdown": round(float(dd), 3)}


# ─────────────────────────────────────────────────────────────
# 3) 분할매수 상태머신 (마틴게일 방지: 탄약·회차 상한)
def dca_plan(confluence: dict, fear_greed: float | None,
             blocked: bool, aggression: str = "공격적",
             max_rounds: int = 5, ammo_per_round: float = 0.18,
             fg_enter: int = 25, fg_extreme: int = 15) -> dict:
    """현재 시점의 매수 행동 제안.
    blocked=True(폭락장 차단)면 조정매수 중단."""
    if blocked:
        return {"action": "대기 (폭락장 차단)", "tranche": 0.0,
                "reason": "폭락장 차단기 작동 — 조정 분할매수 중단. "
                          "바닥 포착 모드(장기지지선)로만 진입.",
                "urgency": "blocked"}

    score = confluence["score"]
    # 공격성별 진입 문턱
    thresh = {"공격적": 30, "균형": 45, "보수적": 60}.get(aggression, 45)
    extreme = fear_greed is not None and fear_greed <= fg_extreme

    if score < thresh:
        return {"action": "관망", "tranche": 0.0,
                "reason": f"합류 점수 {score} < 진입 문턱 {thresh} "
                          f"({aggression}). 더 좋은 가격 대기.",
                "urgency": "wait"}

    # 탄약 비중: 극도공포면 1.5배, 점수 비례 가산
    mult = 1.5 if extreme else (1.2 if score >= 60 else 1.0)
    tranche = ammo_per_round * mult
    label = "🔴 적극 매수" if extreme or score >= 70 else "🟡 분할 매수"
    return {"action": label, "tranche": round(tranche, 3),
            "reason": ("극도 공포 + 합류 신호 → 평소보다 큰 트랜치"
                       if extreme else f"합류 점수 {score} → 분할 진입"),
            "urgency": "now" if extreme else "this_week",
            "max_rounds": max_rounds}


# ─────────────────────────────────────────────────────────────
# 4) 폭락장 차단기 — 경고 누적이 임계 넘으면 조정매수 차단
def crash_circuit_breaker(macro: pd.DataFrame, crash_risk_result: dict,
                          stagflation: int | None) -> dict:
    """금리·물가·스태그·신용·유동성 경고를 누적. 임계 넘으면 차단(blocked=True).
    원석님 우려('코로나급 긴 폭락장')의 핵심 안전장치."""
    from core.utils import get_val
    warnings = []

    def warn(cond, label, val):
        if cond:
            warnings.append({"label": label, "val": val})

    # 금리 인상 사이클
    upper = get_val(macro, "DFEDTARU")
    d10_1m = get_val(macro, "DGS10_1M_Chg")
    warn(d10_1m is not None and d10_1m > 0.3, "장기금리 급등", f"{d10_1m:+.2f}%p/월"
         if d10_1m is not None else "")

    # 물가
    cpi = get_val(macro, "CPI_YoY")
    warn(cpi is not None and cpi > 4, "고물가 지속", f"CPI {cpi:.1f}%"
         if cpi is not None else "")

    # 스태그플레이션
    warn(stagflation is not None and stagflation >= 60,
         "스태그플레이션 경고", f"{stagflation}")

    # 신용 경색
    hy = get_val(macro, "BAMLH0A0HYM2")
    hy_chg = get_val(macro, "HY_1M_Chg")
    warn(hy is not None and hy > 5.5, "HY 스프레드 高", f"{hy:.2f}%"
         if hy is not None else "")
    warn(hy_chg is not None and hy_chg > 0.5, "신용 급격 악화",
         f"{hy_chg:+.2f}%p/월" if hy_chg is not None else "")

    # 커브 역전 + 실업 추세전환 동시 (침체 임박 신호)
    t10y3m = get_val(macro, "T10Y3M")
    unrate = macro.get("UNRATE")
    sahm = None
    if unrate is not None and len(unrate.dropna()) > 12:
        u = unrate.dropna()
        sahm = float(u.iloc[-1] - u.tail(12).min())
    warn(t10y3m is not None and t10y3m < -0.5 and sahm is not None and sahm >= 0.3,
         "커브역전+실업상승", f"곡선 {t10y3m:.2f}%, Sahm +{sahm:.2f}" if sahm else "")

    # 1달/1년 폭락 게이지 '높음'
    c1m = crash_risk_result.get("1달", {})
    c1y = crash_risk_result.get("1년", {})
    warn(c1m.get("score") is not None and c1m["score"] >= 67,
         "1달 폭락리스크 높음", f"{c1m.get('score')}")
    warn(c1y.get("score") is not None and c1y["score"] >= 67,
         "1년 폭락리스크 높음", f"{c1y.get('score')}")

    n = len(warnings)
    # 임계: 경고 3개 이상 → 차단, 2개 → 경계(트랜치 축소)
    if n >= 3:
        state, blocked = "차단", True
    elif n >= 2:
        state, blocked = "경계", False
    else:
        state, blocked = "정상", False
    return {"state": state, "blocked": blocked, "n_warnings": n,
            "warnings": warnings,
            "msg": ("🛑 폭락장 차단기 작동 — 조정 분할매수를 중단합니다. "
                    "긴 하락장 가능성에 대비하세요."
                    if blocked else
                    "🟡 경고 누적 중 — 트랜치를 줄이고 신중히 접근하세요."
                    if state == "경계" else
                    "🟢 차단기 정상 — 조정매수 전략 작동 가능.")}


# ─────────────────────────────────────────────────────────────
# 5) 바닥 포착 (폭락장 한정) — 주봉/월봉 장기지지선
def long_term_bottom(close: pd.Series, fear_greed: float | None = None) -> dict:
    """대형주의 주봉/월봉 장기지지선 + 패닉 소진 신호로 바닥 후보 식별.
    폭락장에서만 의미 — 평소엔 참고용."""
    s = close.dropna()
    if len(s) < 300:
        return {"levels": [], "price": None}
    price = float(s.iloc[-1])

    # 주봉 리샘플 후 장기 지지 (200주 MA, 주요 스윙로우)
    wk = s.resample("W-FRI").last().dropna()
    ma200w = wk.rolling(200).mean().iloc[-1] if len(wk) >= 200 else None
    ma100w = wk.rolling(100).mean().iloc[-1] if len(wk) >= 100 else None

    # 월봉 장기 스윙로우 (최근 5년 저점들)
    mo = s.resample("ME").last().dropna()
    swing_lows = []
    if len(mo) >= 12:
        mv = mo.values
        for i in range(3, len(mv) - 3):
            if mv[i] == mv[i - 3:i + 4].min():
                swing_lows.append(float(mv[i]))

    levels = []
    if ma200w and ma200w < price:
        levels.append(("200주 이평", round(ma200w, 1),
                       round((ma200w / price - 1) * 100, 1)))
    if ma100w and ma100w < price:
        levels.append(("100주 이평", round(ma100w, 1),
                       round((ma100w / price - 1) * 100, 1)))
    for lo in sorted(set(round(x, -1) for x in swing_lows if x < price),
                     reverse=True)[:3]:
        levels.append(("월봉 지지", round(lo, 1),
                       round((lo / price - 1) * 100, 1)))

    panic = fear_greed is not None and fear_greed <= 12
    return {"levels": levels, "price": price, "panic": panic,
            "note": ("극도 패닉 + 장기지지선 동시 → 분할 바닥매수 후보"
                     if panic and levels else
                     "장기지지선 도달 시 분할 진입 고려")}


# ─────────────────────────────────────────────────────────────
# 6) 백테스트 — 과거 공포구간 분할매수 vs 일괄매수(Lump-sum)
def backtest_dca(close: pd.Series, fg_proxy: pd.Series, start: str,
                 aggression: str = "공격적", fg_enter: int = 25,
                 max_rounds: int = 5, ammo_per_round: float = 0.18,
                 cooldown_days: int = 20) -> dict | None:
    """공포구간 분할매수 전략의 과거 성과.
    fg_proxy: 공포탐욕 대용 시계열(0~100, VIX 퍼센타일 역수 등).
    비교군: 같은 자본을 시작일에 한번에(Lump-sum) / 매월 정액(DCA-fixed).
    핵심 질문 = '공포에 타이밍 잡는 게 단순 적립보다 나은가?'"""
    s = close.dropna()
    fg = fg_proxy.reindex(s.index).ffill()
    s = s.loc[start:]
    fg = fg.loc[start:]
    if len(s) < 120:
        return None

    thresh = {"공격적": 30, "균형": 45, "보수적": 60}.get(aggression, 45)

    # ── 전략: 공포+합류 시 탄약 투입 (회차/탄약 상한)
    cash = 1.0                                   # 총 탄약 1.0
    shares = 0.0
    rounds = 0
    last_buy = None
    buys = []
    for i in range(60, len(s)):
        if rounds >= max_rounds or cash <= 1e-6:
            break
        dt = s.index[i]
        if last_buy is not None and (dt - last_buy).days < cooldown_days:
            continue
        fgv = fg.iloc[i]
        if fgv is None or fgv != fgv:
            continue
        sub = s.iloc[:i + 1]
        conf = confluence_score(sub, float(fgv))
        if conf["score"] >= thresh:
            mult = 1.5 if fgv <= 15 else (1.2 if conf["score"] >= 60 else 1.0)
            amt = min(cash, ammo_per_round * mult)
            shares += amt / s.iloc[i]
            cash -= amt
            rounds += 1
            last_buy = dt
            buys.append({"date": dt.date(), "price": round(float(s.iloc[i]), 1),
                         "fg": round(float(fgv)), "amt": round(amt, 3),
                         "score": conf["score"]})
    # 남은 현금은 마지막에 투입 안 함(보수적) → 전략 자본효율 페널티 반영
    strat_val = shares * float(s.iloc[-1]) + cash

    # ── 비교군 1: Lump-sum (시작일 전액)
    lump_shares = 1.0 / float(s.iloc[0])
    lump_val = lump_shares * float(s.iloc[-1])

    # ── 비교군 2: 매월 정액 적립 (DCA-fixed)
    monthly = s.resample("ME").first().dropna()
    n_months = len(monthly)
    per = 1.0 / n_months if n_months else 0
    fixed_shares = sum(per / p for p in monthly.values)
    fixed_val = fixed_shares * float(s.iloc[-1])

    return {
        "strategy_return": strat_val - 1.0,
        "lump_return": lump_val - 1.0,
        "fixed_dca_return": fixed_val - 1.0,
        "buys": pd.DataFrame(buys),
        "rounds_used": rounds,
        "cash_unused": round(cash, 3),
        "note": ("공포구간 분할매수 vs 일괄매수 vs 매월적립 비교. "
                 "전략이 일괄매수를 못 이기면 '타이밍 노력'이 무의미하다는 뜻 — "
                 "강세장에선 보통 일찍 다 넣는 게 유리하고, 변동성 큰 장에서 "
                 "분할매수 우위가 드러납니다. 미투입 현금은 전략 수익률에 페널티로 반영됨."),
    }
