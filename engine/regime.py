# engine/regime.py — 7축 레짐 분류 + 히스테리시스 (§9-1)
import pandas as pd

from core.utils import get_val


def classify_axes(macro: pd.DataFrame, vix: float | None, liq: dict) -> list[dict]:
    """각 축: {axis, state, score, detail}"""
    axes = []

    # 1) 유동성 — v18: liq_z + 가속도 기반 (engine/liquidity.liquidity_state)
    axes.append({"axis": "유동성", "state": liq["state"], "score": liq["score"],
                 "detail": f"1M변화 z={liq['z']:.2f}" if liq["z"] is not None else "데이터 없음"})

    # 2) 변동성 (VIX)
    if vix is None:
        axes.append({"axis": "변동성", "state": "Unknown", "score": 0, "detail": "VIX 없음"})
    elif vix <= 20:
        axes.append({"axis": "변동성", "state": "Calm", "score": +1.0, "detail": f"VIX {vix:.1f}"})
    elif vix < 30:
        axes.append({"axis": "변동성", "state": "Elevated", "score": -0.5, "detail": f"VIX {vix:.1f}"})
    else:
        axes.append({"axis": "변동성", "state": "High", "score": -1.5, "detail": f"VIX {vix:.1f}"})

    # 3) 신용 (HY 스프레드 1M 변화)
    hy = get_val(macro, "HY_1M_Chg")
    if hy is None:
        axes.append({"axis": "신용", "state": "Unknown", "score": 0, "detail": "—"})
    elif hy <= 0:
        axes.append({"axis": "신용", "state": "Easing", "score": +1.0, "detail": f"HY 1M {hy:+.2f}%p"})
    else:
        axes.append({"axis": "신용", "state": "Rising", "score": -1.0, "detail": f"HY 1M {hy:+.2f}%p"})

    # 4) 금융환경 (NFCI)
    nfci = get_val(macro, "NFCI")
    if nfci is None:
        axes.append({"axis": "금융환경", "state": "Unknown", "score": 0, "detail": "—"})
    elif nfci < 0:
        axes.append({"axis": "금융환경", "state": "Loose", "score": +0.5, "detail": f"NFCI {nfci:.2f}"})
    else:
        axes.append({"axis": "금융환경", "state": "Tight", "score": -0.5, "detail": f"NFCI {nfci:.2f}"})

    # 5) 금리커브
    curve = get_val(macro, "T10Y2Y")
    if curve is None:
        axes.append({"axis": "금리커브", "state": "Unknown", "score": 0, "detail": "—"})
    elif curve >= 0:
        axes.append({"axis": "금리커브", "state": "Normal", "score": +0.5, "detail": f"10Y-2Y {curve:+.2f}%"})
    else:
        axes.append({"axis": "금리커브", "state": "Inverted", "score": -0.5, "detail": f"10Y-2Y {curve:+.2f}%"})

    # 6) M2 성장
    m2 = get_val(macro, "M2_YoY")
    if m2 is None:
        axes.append({"axis": "M2", "state": "Unknown", "score": 0, "detail": "—"})
    elif m2 > 5:
        axes.append({"axis": "M2", "state": "Expanding", "score": +0.5, "detail": f"YoY {m2:.1f}%"})
    elif m2 < 0:
        axes.append({"axis": "M2", "state": "Contracting", "score": -0.3, "detail": f"YoY {m2:.1f}%"})
    else:
        axes.append({"axis": "M2", "state": "Moderate", "score": 0.0, "detail": f"YoY {m2:.1f}%"})

    # 7) 인플레이션 (패널티만)
    cpi = get_val(macro, "CPI_YoY")
    if cpi is not None and cpi > 4:
        axes.append({"axis": "인플레이션", "state": "High", "score": -0.5, "detail": f"CPI YoY {cpi:.1f}%"})
    else:
        axes.append({"axis": "인플레이션", "state": "Contained", "score": 0.0,
                     "detail": f"CPI YoY {cpi:.1f}%" if cpi is not None else "—"})
    return axes


def raw_label(score: float) -> str:
    if score >= 1.0:
        return "Risk-On"
    if score <= -1.0:
        return "Risk-Off"
    return "Mixed"


def apply_hysteresis(prev: str | None, score: float) -> str:
    """§9-1: 전환에 ±1.5 마진 요구 → 경계 왕복(whipsaw) 방지"""
    if prev == "Risk-On":
        if score <= -1.5:
            return "Risk-Off"
        if score < 0.0:
            return "Mixed"
        return "Risk-On"
    if prev == "Risk-Off":
        if score >= 1.5:
            return "Risk-On"
        if score > 0.0:
            return "Mixed"
        return "Risk-Off"
    return raw_label(score)


def regime_summary(axes: list[dict], prev: str | None) -> dict:
    score = round(sum(a["score"] for a in axes), 2)
    label = apply_hysteresis(prev, score)
    strength = "강한 " if abs(score) >= 2.5 and label != "Mixed" else ""
    return {"score": score, "label": label, "display": strength + label,
            "raw_label": raw_label(score), "axes": axes,
            "hysteresis_active": prev is not None and raw_label(score) != label}
