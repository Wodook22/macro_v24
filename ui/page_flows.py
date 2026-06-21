# ui/page_flows.py — 크로스에셋 자금흐름 "유동성이 어디로 이동하는가" (§5)
import plotly.graph_objects as go
import streamlit as st

from core.config import FLOW_UNIVERSE, FLOW_BENCH, FLOW_RATIOS, FLOW_RATIO_TICKERS
from core.utils import fmt_pct
from data.market import fetch_prices
from data.crypto import fetch_stablecoin_mcap, fetch_global
from engine.flows import rrg_coords, rrg_table, flow_ratios, flow_summary

QUAD_COLOR = {"주도(Leading)": "#2ecc71", "약화(Weakening)": "#f1c40f",
              "개선(Improving)": "#4da6ff", "침체(Lagging)": "#e74c3c"}


def render():
    st.title("🔀 자금흐름 — 유동성이 어디로 이동하는가")

    tickers = tuple(set(list(FLOW_UNIVERSE.values()) + [FLOW_BENCH] + FLOW_RATIO_TICKERS))
    close, _ = fetch_prices(tickers, "2y")
    if close.empty:
        st.error("가격 데이터 로드 실패")
        return
    rename = {v: k for k, v in FLOW_UNIVERSE.items()}
    cl = close.rename(columns=rename)
    # 벤치마크 fallback: ACWI 다운로드 실패 시 SPY 사용 (Cloud의 yfinance 부분실패 대응)
    bench = next((b for b in [FLOW_BENCH, "SPY", "QQQ"] if b in cl.columns), None)
    universe_cols = [c for c in list(FLOW_UNIVERSE.keys()) + [bench]
                     if c is not None and c in cl.columns]

    lb_tab = st.radio("RRG 룩백", ["63일 (단기 · 선행 감지)", "126일 (장기 · 안정적)"],
                      horizontal=True,
                      help="63일: 추세 전환을 빠르게 포착 (노이즈 多) / "
                           "126일: 안정적이지만 약 3~4주 지연")
    lookback = 63 if "63" in lb_tab else 126
    coords = rrg_coords(cl[universe_cols], bench, lookback=lookback) if bench else {}
    table = rrg_table(coords)

    # 스테이블코인 = 크립토 유동성 직접 프록시
    stable = fetch_stablecoin_mcap()
    stable_chg = None
    if stable is not None and len(stable) > 30:
        stable_chg = float(stable.iloc[-1] - stable.iloc[-30])

    if table.empty:
        st.warning("RRG 계산 불가 — 벤치마크/자산 가격 데이터가 부족합니다. "
                   "yfinance 일시 실패일 수 있으니 잠시 후 새로고침하거나 "
                   "'데이터 품질' 페이지를 확인하세요. 아래 프록시 지표는 계속 표시됩니다.")
    else:
        if bench != FLOW_BENCH:
            st.caption(f"ℹ️ 벤치마크 {FLOW_BENCH} 데이터 누락 → **{bench}** 로 대체 계산")
        st.info(f"**이번 주 요약** — {flow_summary(table, stable_chg)}")

    # ── RRG 차트 (결과 있을 때만)
    if not table.empty:
        fig = go.Figure()
        fig.add_hline(y=100, line_dash="dot", line_color="gray")
        fig.add_vline(x=100, line_dash="dot", line_color="gray")
        for a, df in coords.items():
            q = table.set_index("자산").loc[a, "사분면"] if a in table["자산"].values else "—"
            color = QUAD_COLOR.get(q, "#aaa")
            fig.add_scatter(x=df["rs"], y=df["mom"], mode="lines",
                            line=dict(color=color, width=1), opacity=0.45,
                            showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=[df["rs"].iloc[-1]], y=[df["mom"].iloc[-1]],
                            mode="markers+text", text=[a], textposition="top center",
                            marker=dict(color=color, size=10), name=a, showlegend=False)
        fig.add_annotation(x=0.99, y=0.99, xref="paper", yref="paper",
                           text="주도", showarrow=False, font=dict(color="#2ecc71"))
        fig.add_annotation(x=0.99, y=0.01, xref="paper", yref="paper",
                           text="약화", showarrow=False, font=dict(color="#f1c40f"))
        fig.add_annotation(x=0.01, y=0.99, xref="paper", yref="paper",
                           text="개선", showarrow=False, font=dict(color="#4da6ff"))
        fig.add_annotation(x=0.01, y=0.01, xref="paper", yref="paper",
                           text="침체", showarrow=False, font=dict(color="#e74c3c"))
        fig.update_layout(height=560, title=f"상대강도 로테이션 (vs {bench}, {lookback}일 룩백, 꼬리 8주)",
                          xaxis_title="RS-Ratio", yaxis_title="RS-Momentum",
                          margin=dict(t=40, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption("궤적이 반시계 방향으로 회전: 개선 → 주도 → 약화 → 침체. "
                   "'개선' 사분면에서 우상향 중인 자산 = 자금 유입 초입.")

        st.dataframe(table, width="stretch", hide_index=True)

    st.divider()

    # ── 프록시 테이블 (§5-2)
    st.subheader("자금흐름 프록시")
    pr = flow_ratios(close, FLOW_RATIOS)
    if not pr.empty:
        pr_show = pr.copy()
        pr_show["1M 변화"] = pr_show["1M 변화"].map(lambda x: fmt_pct(x, 2))
        st.dataframe(pr_show, width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**스테이블코인 시총 (USDT+USDC+DAI)**")
        if stable is not None:
            st.line_chart(stable, height=220)
            if stable_chg is not None:
                d = "유입" if stable_chg > 0 else "이탈"
                st.caption(f"30일 {stable_chg:+.1f} $bn — 크립토로 신규 달러 {d}. "
                           "도미넌스보다 직접적인 유동성 신호.")
        else:
            st.info("CoinGecko 응답 없음")
    with c2:
        st.markdown("**크립토 내부 위험선호**")
        g = fetch_global()
        if g:
            st.metric("BTC 도미넌스", f"{g['btc_dominance']:.1f}%")
            st.metric("전체 시총", f"{g['total_mcap_bn']:,.0f} $bn")
            st.caption("도미넌스 하락 + 시총 상승 = 알트 위험선호 (강한 Risk-On 후반 신호)")
