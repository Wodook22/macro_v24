# engine/risk.py — 포트폴리오 리스크 진단 (v17.1 §11 유지)
import numpy as np
import pandas as pd

from core.config import STRESS_SCENARIOS, asset_class


def portfolio_risk_diagnostics(close: pd.DataFrame, weights: dict,
                               bench: str = "SPY") -> dict | None:
    assets = [a for a in weights if a in close.columns and a != "CASH"]
    if not assets:
        return None
    w = pd.Series({a: weights[a] for a in assets})
    w = w / w.sum()
    rets = close[assets].pct_change().dropna()
    if len(rets) < 60:
        return None
    p_ret = rets @ w
    eq = (1 + p_ret).cumprod()
    out = {
        "연환산 변동성": float(p_ret.std() * np.sqrt(252)),
        "추정 MDD": float((eq / eq.cummax() - 1).min()),
        "일간 VaR95": float(np.percentile(p_ret, 5)),
        "HHI": float((w ** 2).sum()),
    }
    out["일간 CVaR95"] = float(p_ret[p_ret <= out["일간 VaR95"]].mean())
    if bench in close.columns:
        b = close[bench].pct_change().reindex(p_ret.index).dropna()
        pr = p_ret.reindex(b.index)
        var_b = b.var()
        out["SPY 베타"] = float(np.cov(pr, b)[0, 1] / var_b) if var_b else np.nan
    cov = rets.cov() * 252
    port_var = float(w @ cov @ w)
    rc = (w * (cov @ w)) / np.sqrt(port_var) if port_var > 0 else w * 0
    out["위험기여도"] = (rc / rc.sum()).to_dict() if rc.sum() else {}
    out["상관행렬"] = rets.corr()
    return out


def stress_test(weights: dict) -> pd.DataFrame:
    """시나리오별 포트폴리오 손익 (%). CASH는 0% 충격"""
    rows = {}
    for name, shocks in STRESS_SCENARIOS.items():
        pnl = 0.0
        for a, w in weights.items():
            if a == "CASH":
                continue
            pnl += w * shocks.get(asset_class(a), shocks.get("equity", 0)) / 100
        rows[name] = pnl
    return pd.DataFrame({"포트폴리오 손익": rows}).sort_values("포트폴리오 손익")
