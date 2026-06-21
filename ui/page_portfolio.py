# ui/page_portfolio.py — 추천 포트폴리오 + 내 포트폴리오 (§1-2/1-3 수정 반영)
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import SECTOR_ETFS, SECTOR_STOCKS
from core.utils import get_val, parse_my_portfolio, fmt_pct
from data.market import fetch_prices
from engine.optimize import (estimate_mu_cov, slsqp_max_sharpe, mc_frontier,
                             calc_cash)
from engine.risk import portfolio_risk_diagnostics, stress_test
from engine.strategy import classify_sleeves, build_barbell, defensive_weight
from ui.common import get_state, get_geo, scored_sectors


def _universe(mode: str, scored: pd.DataFrame, top_n: int) -> tuple[list, dict]:
    etf2name = {v: k for k, v in SECTOR_ETFS.items()}
    top_etfs = list(scored.head(top_n).index)
    groups = {}
    if mode == "Sector ETF Only":
        assets = top_etfs + ["TLT", "GLD"]
        groups = {etf2name.get(e, e): [e] for e in top_etfs}
    elif mode == "Stocks Only":
        assets, groups = [], {}
        for e in top_etfs:
            sec = etf2name.get(e, e)
            picks = SECTOR_STOCKS.get(sec, [])[:3]
            assets += picks
            groups[sec] = picks
        assets += ["TLT", "GLD"]
    else:  # Hybrid
        assets, groups = list(top_etfs), {etf2name.get(e, e): [e] for e in top_etfs}
        for e in top_etfs[:2]:
            sec = etf2name.get(e, e)
            picks = SECTOR_STOCKS.get(sec, [])[:2]
            assets += picks
            groups[sec] = groups.get(sec, []) + picks
        assets += ["TLT", "GLD"]
    return list(dict.fromkeys(assets)), groups


def render():
    st.title("💼 포트폴리오")
    state = get_state()
    reg, liq, macro = state["regime"], state["liq"], state["macro"]
    geo_score, geo_label, _ = get_geo()

    strategy = st.radio(
        "전략",
        ["3-슬리브 바벨 (선행+모멘텀+방어)", "SLSQP Max-Sharpe (단기 모멘텀)"],
        horizontal=True,
        help="바벨: 아직 안 오른 선행 섹터 + 이미 강한 모멘텀 + 방어 앵커를 동시 보유. "
             "하락장 방어에 강함. Max-Sharpe: 기존 단기 모멘텀 최적화.")

    if strategy.startswith("3-슬리브"):
        _render_barbell(state, geo_score, geo_label)
        return

    mode = st.radio("구성 방식", ["Sector ETF Only", "Stocks Only", "Hybrid ETF + Stocks"],
                    horizontal=True)
    scored = scored_sectors(state)
    if scored.empty:
        st.error("섹터 스코어 계산 실패")
        return
    assets, groups = _universe(mode, scored, st.session_state.get("top_n", 3))

    close, _ = fetch_prices(tuple(assets + ["SPY"]), st.session_state.get("period", "2y"))
    avail = [a for a in assets if a in close.columns and close[a].dropna().shape[0] > 130]
    if len(avail) < 3:
        st.error("최적화 가능한 자산 부족")
        return
    rets = close[avail].pct_change().dropna()
    mu, cov = estimate_mu_cov(rets)

    # 동적 현금 (§4 지정학 자동점수 연동)
    hy = get_val(macro, "HY_1M_Chg")
    nfci = get_val(macro, "NFCI")
    cash_w = calc_cash(state["vix"], reg["label"], liq["state"],
                       credit_stress=(hy is not None and hy > 0.1),
                       nfci_tight=(nfci is not None and nfci > 0),
                       geo_score=geo_score)

    max_asset = st.session_state.get("max_asset", 0.25)
    max_sector = st.session_state.get("max_sector", 0.45)
    rf = st.session_state.get("rf", 0.04)

    w_risky = slsqp_max_sharpe(mu, cov, rf=rf, max_asset=max_asset,
                               sector_groups=groups, max_sector=max_sector)
    weights = (w_risky * (1 - cash_w)).round(4).to_dict()
    weights["CASH"] = round(cash_w, 4)
    st.session_state["_rec_weights"] = weights

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("추천 비중 (SLSQP Max-Sharpe)")
        wdf = (pd.Series(weights).sort_values(ascending=False)
               .rename("비중").to_frame())
        wdf["비중"] = wdf["비중"].map(lambda x: fmt_pct(x, 1))
        st.dataframe(wdf, width="stretch")
        st.caption(f"현금 {cash_w*100:.0f}% — VIX/레짐/유동성/신용/지정학({geo_label}) 반영. "
                   f"단일자산 ≤ {max_asset*100:.0f}%, 단일섹터 ≤ {max_sector*100:.0f}% "
                   "**제약이 실제로 강제됨** (v17.1 버그 수정)")
        st.warning("Max-Sharpe는 기대수익 추정오차에 민감합니다. 결과는 '정답'이 아니라 "
                   "출발점이며, 데이터 1~2주 차이로 비중이 흔들릴 수 있습니다.", icon="⚠️")
    with c2:
        st.subheader("효율적 프론티어 (시각화용 MC)")
        fr = mc_frontier(mu, cov, rf=rf, max_asset=max_asset)
        pr = float(w_risky @ mu)
        pv = float((w_risky @ cov @ w_risky) ** 0.5)
        fig = go.Figure()
        fig.add_scatter(x=fr["vol"], y=fr["ret"], mode="markers",
                        marker=dict(size=4, color=fr["sharpe"], colorscale="Viridis",
                                    showscale=True, colorbar=dict(title="Sharpe")),
                        name="시뮬레이션")
        fig.add_scatter(x=[pv], y=[pr], mode="markers",
                        marker=dict(size=14, color="red", symbol="star"),
                        name="SLSQP 최적해")
        fig.update_layout(height=380, xaxis_title="변동성", yaxis_title="기대수익",
                          margin=dict(t=20, b=10))
        st.plotly_chart(fig, width="stretch")

    # 추천 포트 리스크 진단
    diag = portfolio_risk_diagnostics(close, weights)
    if diag:
        st.subheader("리스크 진단 (추천 포트폴리오)")
        m = st.columns(5)
        m[0].metric("연환산 변동성", fmt_pct(diag["연환산 변동성"]))
        m[1].metric("SPY 베타", f"{diag.get('SPY 베타', float('nan')):.2f}")
        m[2].metric("일간 VaR95", fmt_pct(diag["일간 VaR95"], 2))
        m[3].metric("일간 CVaR95", fmt_pct(diag["일간 CVaR95"], 2))
        m[4].metric("집중도 HHI", f"{diag['HHI']:.3f}")

    st.divider()

    # ── 내 포트폴리오
    st.subheader("👤 내 포트폴리오 vs 추천")
    txt = st.text_area("보유 입력 (티커:비중%, 줄바꿈 구분)", "NVDA:20\nQQQ:30\nTLT:20\nCASH:30",
                       height=120)
    total_value = st.number_input("총 평가금액 ($)", value=10000, step=1000)
    mine = parse_my_portfolio(txt)
    if mine:
        st.session_state["_my_weights"] = mine
        all_assets = sorted(set(mine) | set(weights))
        comp = pd.DataFrame({
            "내 비중": [mine.get(a, 0) for a in all_assets],
            "추천 비중": [weights.get(a, 0) for a in all_assets]}, index=all_assets)
        comp["차이"] = comp["추천 비중"] - comp["내 비중"]
        comp["리밸런싱 금액 ($)"] = (comp["차이"] * total_value).round(0)
        comp_show = comp.copy()
        for c in ["내 비중", "추천 비중", "차이"]:
            comp_show[c] = comp_show[c].map(lambda x: fmt_pct(x, 1))
        st.dataframe(comp_show, width="stretch")

        my_tickers = [a for a in mine if a != "CASH"]
        cl2, _ = fetch_prices(tuple(set(my_tickers + ["SPY"])), "1y")
        d2 = portfolio_risk_diagnostics(cl2, mine) if not cl2.empty else None
        if d2:
            st.session_state["_my_var95"] = d2["일간 VaR95"]
            k = st.columns(4)
            k[0].metric("내 포트 변동성", fmt_pct(d2["연환산 변동성"]))
            k[1].metric("내 포트 베타", f"{d2.get('SPY 베타', float('nan')):.2f}")
            k[2].metric("내 포트 VaR95", fmt_pct(d2["일간 VaR95"], 2))
            k[3].metric("내 포트 HHI", f"{d2['HHI']:.3f}")

        st.subheader("스트레스 테스트 (내 포트폴리오)")
        stx = stress_test(mine)
        stx_show = stx.copy()
        stx_show["포트폴리오 손익"] = stx_show["포트폴리오 손익"].map(lambda x: fmt_pct(x, 1))
        st.dataframe(stx_show, width="stretch")
        st.caption("시나리오 충격은 자산군 단순 매핑 기반 추정치입니다. 정밀 분석이 아닌 "
                   "방향성 점검용으로만 사용하세요.")


# ─────────────────────────────────────────────────────────────
# 3-슬리브 바벨 전략 렌더링
def _render_barbell(state: dict, geo_score: int, geo_label: str):
    from core.config import SECTOR_ETFS, AI_BASKET
    reg, liq = state["regime"], state["liq"]
    vix = state["vix"]

    # 유니버스: 섹터 ETF + AI 바스켓 일부 + 방어자산 + 벤치
    ai_top = sorted({t for v in AI_BASKET.values() for t in v})[:12]
    universe = sorted(set(list(SECTOR_ETFS.values()) + ai_top
                          + ["TLT", "IEF", "GLD", "XLP", "XLU", "XLV", "SHY", "SPY"]))
    close, _ = fetch_prices(tuple(universe), st.session_state.get("period", "2y"))
    if close.empty or "SPY" not in close.columns:
        st.error("가격 데이터 로드 실패")
        return

    sleeves = classify_sleeves(close, bench="SPY")
    if sleeves.empty:
        st.warning("RRG 슬리브 분류 불가 — 데이터 부족. 잠시 후 새로고침하세요.")
        return

    # 1달 폭락 리스크 → 방어 비중 연동
    crash_1m = None
    try:
        from data.fred import buffett_indicator
        from engine.risk_radar import crash_risk, stagflation_score
        bf = buffett_indicator()
        bf_z = float(bf["z"].iloc[-1]) if bf is not None and not bf.empty else None
        stag = stagflation_score(state["macro"])
        crash = crash_risk(state["macro"], vix, close.get("SPY"), bf_z,
                           stag["score"] if stag["score"] is not None else None)
        crash_1m = crash.get("1달", {}).get("score")
    except Exception:                            # noqa: BLE001
        pass

    bar = build_barbell(close, sleeves, reg["label"], vix, liq["state"],
                        geo_score=geo_score,
                        top_each=st.session_state.get("top_n", 3), bench="SPY",
                        crash_1m=crash_1m)
    weights = bar["weights"]
    st.session_state["_rec_weights"] = weights

    if crash_1m is not None and crash_1m >= 34:
        st.warning(f"⚠️ 1달 폭락 리스크 {crash_1m}점 감지 → 방어 앵커 비중을 "
                   f"자동 상향했습니다. (리스크 레이더 페이지에서 상세 확인)")

    # ── 슬리브 배분 요약
    st.subheader("슬리브 배분")
    alloc = bar["sleeve_alloc"]
    c1, c2, c3 = st.columns(3)
    c1.metric("🌱 선행 (개선)", fmt_pct(alloc["선행"]),
              help="아직 안 올랐지만 모멘텀이 돌아서는 섹터 — 유동성 유입 초입")
    c2.metric("🚀 모멘텀 (주도)", fmt_pct(alloc["모멘텀"]),
              help="이미 강한 추세 — 추세품질 필터 통과분만")
    c3.metric("🛡️ 방어 앵커", fmt_pct(alloc["방어"]),
              help=f"레짐({reg['label']})·VIX·유동성 연동 동적 비중 — 하락장 방어")

    tilt = bar["tilt"]
    st.caption(
        f"현재 레짐 **{reg['display']}** → 성장 예산을 선행 {tilt['lead_share']*100:.0f}% / "
        f"모멘텀 {tilt['mom_share']*100:.0f}%로 배분. "
        + ("약세장이라 저평가 선행 섹터 비중을 높였습니다."
           if reg["label"] == "Risk-Off" else
           "강세장이라 모멘텀 비중을 높이고 방어를 축소했습니다."
           if reg["label"] == "Risk-On" else
           "중립 구간이라 선행·모멘텀을 균등 배분했습니다."))

    # ── 슬리브별 선택 종목
    st.subheader("슬리브별 선택")
    etf2name = {v: k for k, v in SECTOR_ETFS.items()}
    def _label(t):
        return f"{t} ({etf2name[t]})" if t in etf2name else t

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("**🌱 선행 슬리브**")
        if bar["picks"]["선행"]:
            for t in bar["picks"]["선행"]:
                row = sleeves.loc[t]
                st.write(f"- {_label(t)}  \n  RS {row['rs']:.0f} · 모멘텀 {row['mom']:.0f} "
                         f"· 회귀점수 {row['mr_score']:+.1f}")
        else:
            st.caption("개선 사분면 후보 없음 → 방어로 회수")
    with s2:
        st.markdown("**🚀 모멘텀 슬리브**")
        if bar["picks"]["모멘텀"]:
            for t in bar["picks"]["모멘텀"]:
                row = sleeves.loc[t]
                st.write(f"- {_label(t)}  \n  RS {row['rs']:.0f} · 모멘텀 {row['mom']:.0f} "
                         f"· 추세품질 {row['tq_score']:+.1f}")
        else:
            st.caption("주도 사분면 후보 없음 → 방어로 회수")
    with s3:
        st.markdown("**🛡️ 방어 앵커**")
        for t in bar["picks"]["방어"]:
            st.write(f"- {_label(t)}")

    # ── 전체 비중 + 차트
    st.subheader("최종 비중")
    cc1, cc2 = st.columns([1, 1])
    with cc1:
        wser = pd.Series(weights).sort_values(ascending=False)
        wdf = wser.rename("비중").to_frame()
        wdf["비중"] = wdf["비중"].map(lambda x: fmt_pct(x, 1))
        wdf.insert(0, "자산", [_label(t) for t in wser.index])
        st.dataframe(wdf, width="stretch", hide_index=True)
    with cc2:
        # 슬리브별 색상 파이
        sleeve_of = {}
        for t in weights:
            if t in bar["picks"]["선행"]:
                sleeve_of[t] = "선행"
            elif t in bar["picks"]["모멘텀"]:
                sleeve_of[t] = "모멘텀"
            else:
                sleeve_of[t] = "방어"
        cmap = {"선행": "#4da6ff", "모멘텀": "#1d9e75", "방어": "#888780"}
        fig = go.Figure(go.Pie(
            labels=[_label(t) for t in weights],
            values=list(weights.values()),
            marker=dict(colors=[cmap[sleeve_of[t]] for t in weights]),
            textinfo="label+percent", textfont_size=11, hole=0.4))
        fig.update_layout(height=360, margin=dict(t=10, b=10),
                          showlegend=False,
                          annotations=[dict(text="3-슬리브", x=0.5, y=0.5,
                                            font_size=14, showarrow=False)])
        st.plotly_chart(fig, width="stretch")

    # ── 리스크 진단
    diag = portfolio_risk_diagnostics(close, weights)
    if diag:
        st.subheader("리스크 진단")
        m = st.columns(5)
        m[0].metric("연환산 변동성", fmt_pct(diag["연환산 변동성"]))
        m[1].metric("SPY 베타", f"{diag.get('SPY 베타', float('nan')):.2f}")
        m[2].metric("일간 VaR95", fmt_pct(diag["일간 VaR95"], 2))
        m[3].metric("일간 CVaR95", fmt_pct(diag["일간 CVaR95"], 2))
        m[4].metric("집중도 HHI", f"{diag['HHI']:.3f}")
        beta = diag.get("SPY 베타")
        if beta is not None and beta < 0.85:
            st.success(f"✅ SPY 베타 {beta:.2f} — 시장보다 낮은 민감도로 하락장 충격이 완화됩니다.")

    # ── 스트레스 테스트
    st.subheader("스트레스 테스트")
    stx = stress_test(weights)
    stx_show = stx.copy()
    stx_show["포트폴리오 손익"] = stx_show["포트폴리오 손익"].map(lambda x: fmt_pct(x, 1))
    st.dataframe(stx_show, width="stretch")
    st.caption("💡 이 전략은 '주식 급락' 시나리오에서 방어 앵커(채권·금) 덕분에 "
               "SPY 단독 대비 손실이 작게 설계되어 있습니다. "
               "백테스트 페이지에서 SPY 대비 실제 성과를 검증하세요.")
