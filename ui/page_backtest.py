# ui/page_backtest.py — 전략 백테스트 (바벨 vs SPY vs 모멘텀 비교)
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import SECTOR_ETFS, AI_BASKET, DEFAULT_SCORE_W
from core.utils import fmt_pct
from data.market import fetch_prices
from engine.backtest import run_backtest, run_barbell_backtest


def _stat_fmt(k, v):
    if v is None:
        return "—"
    return f"{v:.2f}" if ("Sharpe" in k or "Sortino" in k) else fmt_pct(v)


def render():
    st.title("⏪ 백테스트")

    c1, c2, c3 = st.columns(3)
    years = c1.slider("기간 (년)", 2, 10, 5)
    top_n = c2.slider("슬리브별 종목 수", 1, 6,
                      int(st.session_state.get("top_n") or 3))
    cost_bps = c3.number_input("왕복 거래비용 (bp)", 0.0, 50.0,
                               float(st.session_state.get("cost_bps") or 5.0),
                               step=1.0)

    compare = st.checkbox("기존 모멘텀 전략도 함께 비교", value=True)

    period = f"{years + 2}y"  # 룩백(200MA + RRG 126일) 여유 +2년
    with st.spinner("데이터 로드 / 시뮬레이션 중..."):
        ai_top = sorted({t for v in AI_BASKET.values() for t in v})[:12]
        universe = sorted(set(list(SECTOR_ETFS.values()) + ai_top
                              + ["TLT", "IEF", "GLD", "XLP", "XLU", "XLV",
                                 "SHY", "SPY", "^VIX"]))
        close, _ = fetch_prices(tuple(universe), period)
        if close.empty or "SPY" not in close.columns:
            st.error("가격 데이터 로드 실패")
            return
        start = (pd.Timestamp.today() - pd.DateOffset(years=years)) \
            .strftime("%Y-%m-%d")

        bar = run_barbell_backtest(close, start=start, bench="SPY",
                                   cost_bps=cost_bps, top_each=top_n)
        mom = None
        if compare:
            w = st.session_state.get("score_weights", DEFAULT_SCORE_W)
            mom = run_backtest(close.drop(columns=["^VIX"], errors="ignore"),
                               start=start, top_n=top_n, bench="SPY",
                               cost_bps=cost_bps, weights=w)

    if bar is None:
        st.error("백테스트 실패 — 기간이 너무 짧거나 데이터 부족")
        return

    st.info(bar["note"])

    # ── 에쿼티 커브
    eq, beq = bar["equity"], bar["bench_equity"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=eq, name="3-슬리브 바벨",
                             line=dict(color="#4da6ff", width=2.5)))
    if mom is not None:
        fig.add_trace(go.Scatter(x=mom["equity"].index, y=mom["equity"],
                                 name="기존 모멘텀",
                                 line=dict(color="#1d9e75", width=1.5)))
    fig.add_trace(go.Scatter(x=beq.index, y=beq, name="SPY (Buy&Hold)",
                             line=dict(color="#888", width=1.5, dash="dot")))
    fig.update_layout(height=420, margin=dict(t=30, b=10),
                      yaxis_title="누적수익 (배)", hovermode="x unified",
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, width="stretch")

    # ── 드로다운 커브 (하락장 방어 시각화)
    st.subheader("낙폭 비교 (Drawdown) — 하락장 방어력")
    dd_fig = go.Figure()
    for name, e, color in [("바벨", eq, "#4da6ff"), ("SPY", beq, "#888")]:
        dd = e / e.cummax() - 1
        dd_fig.add_trace(go.Scatter(x=dd.index, y=dd * 100, name=name,
                                    fill="tozeroy", line=dict(color=color)))
    dd_fig.update_layout(height=260, margin=dict(t=10, b=10),
                         yaxis_title="고점대비 낙폭 (%)",
                         hovermode="x unified",
                         legend=dict(orientation="h", y=1.12))
    st.plotly_chart(dd_fig, width="stretch")

    # ── 성과 비교표
    st.subheader("성과 요약")
    keys = ["CAGR", "Vol", "Sharpe", "Sortino", "MDD", "월간 승률"]
    cols_data = {"지표": keys,
                 "🌊 바벨": [_stat_fmt(k, bar["stats"].get(k)) for k in keys],
                 "SPY": [_stat_fmt(k, bar["bench_stats"].get(k)) for k in keys]}
    if mom is not None:
        cols_data["모멘텀"] = [_stat_fmt(k, mom["stats"].get(k)) for k in keys]
    order = ["지표", "🌊 바벨"] + (["모멘텀"] if mom is not None else []) + ["SPY"]
    st.dataframe(pd.DataFrame(cols_data)[order], width="stretch",
                 hide_index=True)

    # ── 핵심 인사이트 자동 코멘트
    bar_mdd = bar["stats"].get("MDD")
    spy_mdd = bar["bench_stats"].get("MDD")
    bar_cagr = bar["stats"].get("CAGR")
    spy_cagr = bar["bench_stats"].get("CAGR")
    if None not in (bar_mdd, spy_mdd):
        if bar_mdd > spy_mdd:  # 낙폭 작음 (덜 음수)
            st.success(
                f"✅ **하락장 방어 확인** — 바벨 최대낙폭 {bar_mdd*100:.1f}% vs "
                f"SPY {spy_mdd*100:.1f}%. 고점 대비 손실이 "
                f"{abs(spy_mdd-bar_mdd)*100:.1f}%p 작습니다.")
    if None not in (bar_cagr, spy_cagr):
        if bar_cagr >= spy_cagr:
            st.success(f"✅ **수익도 우위** — 바벨 CAGR {bar_cagr*100:.1f}% ≥ "
                       f"SPY {spy_cagr*100:.1f}%")
        else:
            st.info(f"ℹ️ 바벨 CAGR {bar_cagr*100:.1f}% < SPY {spy_cagr*100:.1f}% — "
                    "절대수익은 낮지만 위험조정수익(Sharpe)과 낙폭방어를 함께 보세요. "
                    "하락장이 적은 기간에선 방어 전략이 불리하게 보일 수 있습니다.")

    # ── 보유 이력
    with st.expander("월별 슬리브 구성 / 거래비용 이력"):
        h = bar["holdings"]
        if h.empty:
            st.caption("이력 없음")
        else:
            st.dataframe(h, width="stretch", hide_index=True)
            st.caption(f"평균 회전비용 {h['비용(bp)'].mean():.1f}bp/월 · "
                       f"총 리밸런싱 {len(h)}회 · "
                       f"평균 방어비중 {h['방어%'].mean():.0f}%")
