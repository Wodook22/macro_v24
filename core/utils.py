# core/utils.py — 공용 유틸
import numpy as np
import pandas as pd
from datetime import datetime

# 데이터 소스 상태 기록 (데이터 품질 페이지에서 표시)
STATUS: dict = {}

def record(source: str, ok: bool, msg: str = ""):
    STATUS[source] = {"ok": ok, "msg": msg,
                      "at": datetime.now().strftime("%m-%d %H:%M")}

def safe_zscore(s: pd.Series, window: int | None = None) -> pd.Series:
    s = pd.Series(s, dtype="float64")
    if window:
        m, sd = s.rolling(window).mean(), s.rolling(window).std()
        return (s - m) / sd.replace(0, np.nan)
    sd = s.std()
    return (s - s.mean()) / (sd if sd and sd == sd else np.nan)

def xsec_z(row: pd.Series) -> pd.Series:
    """크로스섹션(자산 간) z-score"""
    sd = row.std()
    if not sd or sd != sd:
        return row * 0.0
    return (row - row.mean()) / sd

def pct_change_by_calendar(s: pd.Series, periods: int = 12, freq: str = "ME") -> pd.Series:
    """월간/분기 데이터 YoY 정확 계산 (v17.1 버그 1 수정 유지)"""
    m = s.dropna().resample(freq).last()
    return m.pct_change(periods) * 100

def ann_vol(r: pd.Series, window: int = 63) -> pd.Series:
    return r.rolling(window).std() * np.sqrt(252)

def current_drawdown(price: pd.Series, w: int = 126) -> pd.Series:
    return price / price.rolling(w, min_periods=w // 2).max() - 1

def get_val(df: pd.DataFrame, col: str):
    try:
        s = df[col].dropna()
        return float(s.iloc[-1]) if len(s) else None
    except Exception:
        return None

def get_delta(df: pd.DataFrame, col: str, n: int = 1):
    try:
        s = df[col].dropna()
        return float(s.iloc[-1] - s.iloc[-1 - n]) if len(s) > n else None
    except Exception:
        return None

def parse_my_portfolio(text: str) -> dict:
    """'NVDA:20\\nQQQ:30' → {ticker: weight} (합 1로 정규화)"""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        t, w = line.split(":", 1)
        try:
            out[t.strip().upper()] = float(w.strip().replace("%", ""))
        except ValueError:
            continue
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()} if tot > 0 else {}

def perf_stats(equity: pd.Series, freq: int = 252) -> dict:
    equity = equity.dropna()
    if len(equity) < 10:
        return {}
    rets = equity.pct_change().dropna()
    yrs = len(rets) / freq
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / max(yrs, 1e-9)) - 1
    vol = rets.std() * np.sqrt(freq)
    dn = rets[rets < 0].std() * np.sqrt(freq)
    mdd = (equity / equity.cummax() - 1).min()
    monthly = equity.resample("ME").last().pct_change().dropna()
    return {"CAGR": cagr, "Vol": vol,
            "Sharpe": (cagr - 0.04) / vol if vol else np.nan,
            "Sortino": (cagr - 0.04) / dn if dn else np.nan,
            "MDD": mdd,
            "월간 승률": (monthly > 0).mean() if len(monthly) else np.nan}

def fmt_pct(x, d=1):
    return "—" if x is None or x != x else f"{x*100:.{d}f}%"

def fmt_num(x, d=1):
    return "—" if x is None or x != x else f"{x:,.{d}f}"
