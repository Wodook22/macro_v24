# engine/optimize.py — 포트폴리오 최적화 (§1-2, §1-3, §9-2)
# v17.1 치명 버그 수정: clip→정규화 순서 때문에 max_asset 상한이 작동하지 않던 문제
# → SLSQP 제약 최적화로 교체. 몬테카를로는 프론티어 시각화 전용.
import numpy as np
import pandas as pd
from scipy.optimize import minimize


def estimate_mu_cov(rets: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """연율화 기대수익/공분산. 공분산은 Ledoit-Wolf 수축 (실패 시 표본)"""
    rets = rets.dropna()
    mu = rets.mean() * 252
    try:
        from sklearn.covariance import LedoitWolf
        cov = pd.DataFrame(LedoitWolf().fit(rets.values).covariance_ * 252,
                           index=rets.columns, columns=rets.columns)
    except Exception:                            # noqa: BLE001
        cov = rets.cov() * 252
    return mu, cov


def slsqp_max_sharpe(mu: pd.Series, cov: pd.DataFrame, rf: float = 0.04,
                     max_asset: float = 0.25,
                     sector_groups: dict[str, list[str]] | None = None,
                     max_sector: float = 0.45) -> pd.Series:
    assets = list(mu.index)
    n = len(assets)
    mu_v, cov_v = mu.values, cov.values

    def neg_sharpe(w):
        vol = np.sqrt(max(w @ cov_v @ w, 1e-12))
        return -(w @ mu_v - rf) / vol

    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    if sector_groups:                            # §1-3: max_sector 실제 강제
        for sec, members in sector_groups.items():
            idx = [assets.index(a) for a in members if a in assets]
            if len(idx) >= 2:
                cons.append({"type": "ineq",
                             "fun": lambda w, idx=tuple(idx): max_sector - w[list(idx)].sum()})

    bounds = [(0.0, max_asset)] * n
    x0 = np.full(n, 1.0 / n)
    res = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds,
                   constraints=cons, options={"maxiter": 400, "ftol": 1e-9})
    w = res.x if res.success else x0             # 실패 시 등가중 fallback
    w = np.clip(w, 0, None)
    w = w / w.sum()
    return pd.Series(np.round(w, 4), index=assets)


def cap_weights(W: np.ndarray, cap: float, iters: int = 12) -> np.ndarray:
    """초과분 반복 재분배 — MC 표본이 상한을 정확히 만족하도록 (§1-2 수정안 B)"""
    W = W.copy()
    for _ in range(iters):
        over = W > cap
        if not over.any():
            break
        excess = np.where(over, W - cap, 0.0).sum(axis=1, keepdims=True)
        W = np.where(over, cap, W)
        free = ~over
        free_sum = np.where(free, W, 0.0).sum(axis=1, keepdims=True)
        free_sum[free_sum == 0] = 1.0
        W = W + np.where(free, W / free_sum, 0.0) * excess
    return W


def mc_frontier(mu: pd.Series, cov: pd.DataFrame, rf: float = 0.04,
                max_asset: float = 0.25, n_sim: int = 4000,
                seed: int = 42) -> pd.DataFrame:
    """효율적 프론티어 시각화용 (의사결정은 SLSQP가 담당)"""
    rng = np.random.default_rng(seed)
    n = len(mu)
    W = rng.dirichlet(np.ones(n), size=n_sim)
    W = cap_weights(W, max_asset)
    ret = W @ mu.values
    var = np.einsum("ij,jk,ik->i", W, cov.values, W)
    vol = np.sqrt(np.maximum(var, 1e-12))
    return pd.DataFrame({"ret": ret, "vol": vol, "sharpe": (ret - rf) / vol})


def calc_cash(vix: float | None, regime_label: str, liq_state: str,
              credit_stress: bool, nfci_tight: bool, geo_score: int) -> float:
    """동적 현금 비중 (v17.1 유지 + 지정학 자동 점수 연동 §4)"""
    cash = 0.10
    if vix is not None:
        if vix >= 30:
            cash += 0.20
        elif vix >= 25:
            cash += 0.12
        elif vix >= 20:
            cash += 0.06
    if liq_state == "Contracting":
        cash += 0.08
    if credit_stress:
        cash += 0.08
    if nfci_tight:
        cash += 0.05
    if regime_label == "Risk-Off":
        cash += 0.07
    if geo_score >= 65:
        cash += 0.12
    elif geo_score >= 45:
        cash += 0.05
    return float(min(0.50, max(0.05, cash)))
