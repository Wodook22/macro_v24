# engine/flows.py — 크로스에셋 자금흐름 (§5) "유동성이 어디로 이동하는가"
import numpy as np
import pandas as pd


def rrg_coords(close: pd.DataFrame, bench: str, lookback: int = 126,
               mom: int = 21, tail_weeks: int = 8) -> dict[str, pd.DataFrame]:
    """자산별 (RS-Ratio, RS-Momentum) 주간 궤적. 100 기준 4사분면"""
    if bench not in close.columns:
        return {}
    ratio = close.div(close[bench], axis=0)
    rs = 100 * ratio / ratio.rolling(lookback).mean()
    rs_mom = 100 + rs.pct_change(mom) * 100
    out = {}
    for a in close.columns:
        if a == bench:
            continue
        df = pd.DataFrame({"rs": rs[a], "mom": rs_mom[a]}).dropna()
        if df.empty:
            continue
        wk = df.resample("W-FRI").last().dropna().tail(tail_weeks)
        if len(wk) >= 2:
            out[a] = wk
    return out


def quadrant(rs: float, mom: float) -> str:
    if rs >= 100 and mom >= 100:
        return "주도(Leading)"
    if rs >= 100:
        return "약화(Weakening)"
    if mom >= 100:
        return "개선(Improving)"
    return "침체(Lagging)"


RRG_COLS = ["자산", "RS", "모멘텀", "사분면", "모멘텀 변화"]


def rrg_table(coords: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for a, df in coords.items():
        last = df.iloc[-1]
        d_mom = float(df["mom"].iloc[-1] - df["mom"].iloc[0])
        rows.append({"자산": a, "RS": round(float(last["rs"]), 1),
                     "모멘텀": round(float(last["mom"]), 1),
                     "사분면": quadrant(last["rs"], last["mom"]),
                     "모멘텀 변화": round(d_mom, 1)})
    if not rows:                                 # 벤치마크/데이터 부족 시 빈 테이블
        return pd.DataFrame(columns=RRG_COLS)
    return pd.DataFrame(rows).sort_values("모멘텀", ascending=False)


def flow_ratios(close: pd.DataFrame, ratios: dict[str, tuple[str, str]]) -> pd.DataFrame:
    rows = []
    for name, (num, den) in ratios.items():
        if num not in close.columns or den not in close.columns:
            continue
        r = (close[num] / close[den]).dropna()
        if len(r) < 25:
            continue
        chg = r.iloc[-1] / r.iloc[-21] - 1
        rows.append({"프록시": name, "1M 변화": chg,
                     "방향": "▲ 위험선호" if chg > 0.005 else
                            ("▼ 위험회피" if chg < -0.005 else "→ 중립")})
    return pd.DataFrame(rows)


def flow_summary(table: pd.DataFrame, stable_chg_30d: float | None) -> str:
    """§5-3 자동 한 줄 요약 — 에이전트 컨텍스트로도 사용"""
    if table is None or table.empty:
        return "자금흐름 데이터 부족"
    into = table[table["사분면"].isin(["주도(Leading)", "개선(Improving)"])] \
        .sort_values("모멘텀", ascending=False)["자산"].head(3).tolist()
    outof = table[table["사분면"] == "침체(Lagging)"] \
        .sort_values("모멘텀")["자산"].head(3).tolist()
    msg = f"유동성 유입: {', '.join(into) if into else '—'} / 이탈: {', '.join(outof) if outof else '—'}"
    if stable_chg_30d is not None:
        direction = "유입" if stable_chg_30d > 0 else "이탈"
        msg += f" | 스테이블코인 30일 {stable_chg_30d:+.1f}$bn ({direction})"
    return msg
