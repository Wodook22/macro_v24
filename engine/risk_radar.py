# engine/risk_radar.py — 스태그플레이션 / 폭락 리스크 / 연준·금리 경로 (v18.1)
#
# 철학: "폭락 확률"을 점치는 모델은 만들 수 없다(가능하면 누구나 부자).
#       대신 '역사적으로 폭락에 선행했던 조건들이 지금 몇 개나 켜져 있는가'를
#       시간축(1주/1달/1년)별로 집계해 '조건 충족도(0~100)'로 표현한다.
#       이는 확률이 아니라 '경계 수준'이며, 그렇게 표시한다.
import numpy as np
import pandas as pd

from core.utils import get_val, safe_zscore, pct_change_by_calendar


# ─────────────────────────────────────────────────────────────
# 1) 스태그플레이션 리스크
def stagflation_score(macro: pd.DataFrame) -> dict:
    """인플레이션 高 + 성장 둔화 + 고용 악화 동시발생 점수 (0~100).
    각 축을 0~1로 정규화 후 가중 합산."""
    flags = []
    detail = {}

    # 인플레이션: CPI YoY, Core PCE YoY
    cpi_yoy = get_val(macro, "CPI_YoY")
    pce = macro.get("PCEPILFE")
    pce_yoy = None
    if pce is not None and len(pce.dropna()) > 13:
        pce_yoy = float(pct_change_by_calendar(pce.dropna()).dropna().iloc[-1])
    infl_ref = cpi_yoy if cpi_yoy is not None else pce_yoy
    if infl_ref is not None:
        # 2% 정상 → 0, 5%+ → 1.0
        infl_hot = np.clip((infl_ref - 2.0) / 3.0, 0, 1)
        detail["인플레이션"] = {"val": round(infl_ref, 1),
                            "score": round(float(infl_hot), 2),
                            "note": f"CPI/PCE YoY {infl_ref:.1f}%"}
        flags.append(("infl", infl_hot, 0.30))

    # 성장 둔화: 산업생산 YoY (음수일수록 위험)
    indpro = macro.get("INDPRO")
    if indpro is not None and len(indpro.dropna()) > 13:
        ip_yoy = float(pct_change_by_calendar(indpro.dropna()).dropna().iloc[-1])
        # +3% 이상 정상 → 0, -2% 이하 → 1.0
        growth_weak = np.clip((1.0 - ip_yoy) / 5.0, 0, 1)
        detail["성장둔화"] = {"val": round(ip_yoy, 1),
                          "score": round(float(growth_weak), 2),
                          "note": f"산업생산 YoY {ip_yoy:+.1f}%"}
        flags.append(("growth", growth_weak, 0.35))

    # 고용 악화: 실업률 6개월 추세 (상승 = 위험), Sahm rule 근사
    unrate = macro.get("UNRATE")
    if unrate is not None and len(unrate.dropna()) > 13:
        u = unrate.dropna()
        u_now = float(u.iloc[-1])
        u_min12 = float(u.tail(12).min())
        sahm = u_now - u_min12          # Sahm: 저점 대비 +0.5%p면 침체 신호
        emp_bad = np.clip(sahm / 0.7, 0, 1)
        detail["고용악화"] = {"val": round(sahm, 2),
                          "score": round(float(emp_bad), 2),
                          "note": f"실업률 저점대비 +{sahm:.2f}%p (Sahm)"}
        flags.append(("emp", emp_bad, 0.35))

    if not flags:
        return {"score": None, "label": "데이터 부족", "detail": {}}

    wsum = sum(w for _, _, w in flags)
    score = sum(s * w for _, s, w in flags) / wsum * 100
    # 스태그플레이션은 '인플레 高 AND 성장 弱' 동시조건이 핵심 → 둘 다 높을 때 증폭
    infl_s = next((s for k, s, _ in flags if k == "infl"), 0)
    growth_s = next((s for k, s, _ in flags if k == "growth"), 0)
    combo = infl_s * growth_s          # 둘 다 높을 때만 큼
    score = min(100, score * (1 + 0.4 * combo))

    label = ("낮음" if score < 35 else "주의" if score < 60 else "경고")
    return {"score": round(score), "label": label, "detail": detail,
            "combo": round(float(combo), 2)}


# ─────────────────────────────────────────────────────────────
# 2) 연준 대차대조표 분석
def fed_balance_sheet(macro: pd.DataFrame) -> dict:
    """QT 진행 속도, 보유 구성, 지급준비금 비율."""
    out = {}
    walcl = macro.get("WALCL")
    if walcl is not None and len(walcl.dropna()) > 14:
        w = walcl.dropna()
        out["총자산"] = round(float(w.iloc[-1]), 0)
        out["13주 변화"] = round(float(w.iloc[-1] - w.iloc[-14]), 0)  # 약 3개월
        out["QT 진행"] = "축소(QT)" if out["13주 변화"] < -20 else \
                       ("확대(QE)" if out["13주 변화"] > 20 else "중립")
    treast = macro.get("TREAST")
    mbs = macro.get("WSHOMCB")
    if treast is not None and len(treast.dropna()):
        out["보유 국채"] = round(float(treast.dropna().iloc[-1]), 0)
    if mbs is not None and len(mbs.dropna()):
        out["보유 MBS"] = round(float(mbs.dropna().iloc[-1]), 0)
    # 지급준비금/총자산 — 낮아지면 유동성 여유 축소
    wres = macro.get("WRESBAL")
    if wres is not None and walcl is not None:
        r = wres.dropna()
        if len(r) and out.get("총자산"):
            out["지준/총자산"] = round(float(r.iloc[-1]) / out["총자산"] * 100, 1)
    return out


# ─────────────────────────────────────────────────────────────
# 3) 금리 경로 (점도표 근사: 시장 기대 + 현재 정책금리)
def rate_path(macro: pd.DataFrame) -> dict:
    """공식 점도표는 API 없음 → 현재 정책금리 + 국채커브로 시장 기대 경로 근사."""
    out = {}
    upper = get_val(macro, "DFEDTARU")
    eff = get_val(macro, "FEDFUNDS")
    out["정책금리 상단"] = upper
    out["실효 FFR"] = eff
    # 단기물(3M) vs 정책금리: 시장이 인하를 선반영하면 3M < 정책금리
    m3 = get_val(macro, "DGS3MO")
    y2 = get_val(macro, "DGS2")
    y10 = get_val(macro, "DGS10")
    out["3개월"] = m3
    out["2년"] = y2
    out["10년"] = y10
    # 2년 < 정책금리 = 시장이 향후 인하 기대 (2년물은 향후 정책경로 반영)
    if y2 is not None and upper is not None:
        gap = y2 - upper
        out["시장 기대"] = ("인하 선반영" if gap < -0.25 else
                        "인상 선반영" if gap > 0.25 else "현 수준 유지")
        out["2년-정책금리"] = round(gap, 2)
    # 커브 역전 상태
    t10y3m = get_val(macro, "T10Y3M")
    t10y2y = get_val(macro, "T10Y2Y")
    out["10Y-3M"] = t10y3m
    out["10Y-2Y"] = t10y2y
    out["커브 역전"] = bool((t10y3m is not None and t10y3m < 0) or
                        (t10y2y is not None and t10y2y < 0))
    return out


# ─────────────────────────────────────────────────────────────
# 4) 폭락 리스크 게이지 (3 시간축)
def _flag(cond: bool, label: str, val: str) -> dict:
    return {"on": bool(cond), "label": label, "val": val}


def crash_risk(macro: pd.DataFrame, vix: float | None,
               spy_close: pd.Series | None = None,
               buffett_z: float | None = None,
               stagflation: float | None = None) -> dict:
    """3개 시간축별 '역사적 폭락 선행조건' 충족도. 확률 아님."""
    horizons = {}

    # ── 1주: 기술적·변동성 충격
    wk = []
    if vix is not None:
        wk.append(_flag(vix >= 25, "VIX ≥ 25", f"{vix:.1f}"))
        wk.append(_flag(vix >= 30, "VIX ≥ 30 (공포)", f"{vix:.1f}"))
    hy_chg = get_val(macro, "HY_1M_Chg")
    if hy_chg is not None:
        wk.append(_flag(hy_chg > 0.4, "HY 1M 급등", f"{hy_chg:+.2f}%p"))
    if spy_close is not None and len(spy_close.dropna()) > 20:
        s = spy_close.dropna()
        from engine.strategy import rsi
        r = rsi(s)
        ret5 = s.iloc[-1] / s.iloc[-6] - 1 if len(s) > 6 else 0
        wk.append(_flag(r > 78, "SPY RSI 과열", f"{r:.0f}"))
        wk.append(_flag(ret5 < -0.04, "주간 급락 진행", f"{ret5*100:+.1f}%"))
    horizons["1주"] = wk

    # ── 1달: 신용·유동성 경색
    mo = []
    nl = macro.get("Net_Liq")
    if nl is not None and len(nl.dropna()) > 21:
        nlz = safe_zscore(nl.dropna().diff(21), window=252).iloc[-1]
        mo.append(_flag(nlz < -1.0, "순유동성 수축", f"z {nlz:+.1f}"))
    hy = get_val(macro, "BAMLH0A0HYM2")
    if hy is not None:
        mo.append(_flag(hy > 5.0, "HY 스프레드 高", f"{hy:.2f}%"))
    nfci = get_val(macro, "NFCI")
    if nfci is not None:
        mo.append(_flag(nfci > 0, "금융환경 긴축", f"{nfci:+.2f}"))
    stlfsi = get_val(macro, "STLFSI4")
    if stlfsi is not None:
        mo.append(_flag(stlfsi > 0, "금융스트레스 上", f"{stlfsi:+.2f}"))
    if spy_close is not None and len(spy_close.dropna()) > 200:
        s = spy_close.dropna()
        ma200 = s.rolling(200).mean().iloc[-1]
        mo.append(_flag(s.iloc[-1] < ma200, "200일선 이탈",
                        f"{(s.iloc[-1]/ma200-1)*100:+.1f}%"))
    horizons["1달"] = mo

    # ── 1년: 밸류·매크로 사이클
    yr = []
    if buffett_z is not None:
        yr.append(_flag(buffett_z > 1.5, "버핏지표 과열", f"z {buffett_z:+.1f}"))
    t10y3m = get_val(macro, "T10Y3M")
    if t10y3m is not None:
        yr.append(_flag(t10y3m < 0, "10Y-3M 역전", f"{t10y3m:+.2f}%"))
    if stagflation is not None:
        yr.append(_flag(stagflation >= 60, "스태그플레이션 경고", f"{stagflation:.0f}"))
    # 실업률 추세전환 (Sahm)
    unrate = macro.get("UNRATE")
    if unrate is not None and len(unrate.dropna()) > 12:
        u = unrate.dropna()
        sahm = float(u.iloc[-1] - u.tail(12).min())
        yr.append(_flag(sahm >= 0.5, "실업률 추세전환", f"+{sahm:.2f}%p"))
    horizons["1년"] = yr

    # 점수화: 켜진 조건 / 전체 조건
    result = {}
    for h, flags in horizons.items():
        flags = [f for f in flags if f is not None]
        if not flags:
            result[h] = {"score": None, "label": "데이터 부족",
                         "on": 0, "total": 0, "flags": []}
            continue
        on = sum(f["on"] for f in flags)
        score = round(on / len(flags) * 100)
        label = ("낮음" if score < 34 else "경계" if score < 67 else "높음")
        result[h] = {"score": score, "label": label, "on": on,
                     "total": len(flags), "flags": flags}
    return result


def crash_summary(crash: dict) -> str:
    parts = []
    for h in ["1주", "1달", "1년"]:
        r = crash.get(h, {})
        if r.get("score") is not None:
            parts.append(f"{h} {r['label']}({r['on']}/{r['total']})")
    return " · ".join(parts) if parts else "데이터 부족"
