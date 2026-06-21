# engine/liquidity.py — Net Liquidity 2.0 (§2)
# v17.1 버그 4의 근본 해결: 전부 주간(W-WED) 정렬 → diff(1)=1주, diff(4)≈1개월
import pandas as pd

from core.utils import safe_zscore


def weekly_liquidity(macro: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["WALCL", "TGA", "RRPONTSYD", "WRESBAL", "Net_Liq"] if c in macro]
    if macro.empty or not cols or not isinstance(macro.index, pd.DatetimeIndex):
        return pd.DataFrame()                    # FRED 전체 실패 시 graceful
    w = macro[cols].resample("W-WED").last().dropna(subset=["Net_Liq"], how="any") \
        if "Net_Liq" in cols else macro[cols].resample("W-WED").last()
    if "Net_Liq" not in w:
        return w
    w["chg_1w"] = w["Net_Liq"].diff(1)
    w["chg_1m"] = w["Net_Liq"].diff(4)
    w["MA4"] = w["Net_Liq"].rolling(4).mean()
    w["MA12"] = w["Net_Liq"].rolling(12).mean()
    # §2-3 유동성 임팩트: 1개월 변화의 1년(52주) z-score + 가속도
    w["liq_z"] = safe_zscore(w["chg_1m"], window=52)
    w["accel"] = w["chg_1m"].diff(4)
    return w


def liquidity_state(w: pd.DataFrame) -> dict:
    """레짐 분류의 '유동성 축' 입력값 (§부록A: MA20 단순비교 → z+가속도)"""
    if w is None or w.empty or "liq_z" not in w:
        return {"state": "Unknown", "score": 0.0, "z": None, "accel": None}
    z = w["liq_z"].dropna()
    a = w["accel"].dropna()
    z_now = float(z.iloc[-1]) if len(z) else None
    a_now = float(a.iloc[-1]) if len(a) else None
    if z_now is None:
        return {"state": "Unknown", "score": 0.0, "z": None, "accel": a_now}
    if z_now > 0.3 and (a_now is None or a_now >= 0):
        return {"state": "Expanding", "score": +1.5, "z": z_now, "accel": a_now}
    if z_now < -0.3:
        return {"state": "Contracting", "score": -1.5, "z": z_now, "accel": a_now}
    return {"state": "Neutral", "score": 0.0, "z": z_now, "accel": a_now}
