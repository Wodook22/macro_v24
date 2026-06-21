# ui/page_liquidity.py — Net Liquidity 2.0 + 단기 국채발행 (§2, §3)
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.utils import get_val
from data.treasury import (fetch_bill_flows, fetch_auctions, fetch_tga_daily,
                           bill_liquidity_matrix)
from ui.common import get_state


def render():
    st.title("💧 유동성 모니터 — Net Liquidity 2.0")
    state = get_state()
    macro, wliq, liq = state["macro"], state["wliq"], state["liq"]

    # ── 순유동성 (주간 정렬)
    c1, c2, c3 = st.columns(3)
    if "Net_Liq" in wliq:
        nl = wliq["Net_Liq"].dropna()
        chg = wliq["chg_1m"].dropna()
        if len(nl):
            c1.metric("순유동성", f"{nl.iloc[-1]:,.0f} $bn",
                      f"1M {chg.iloc[-1]:+,.0f} $bn" if len(chg) else None)
    c2.metric("유동성 임팩트 z", f"{liq['z']:+.2f}" if liq["z"] is not None else "—",
              liq["state"])
    rrp = get_val(macro, "RRPONTSYD")
    c3.metric("역레포 RRP", f"{rrp:,.0f} $bn" if rrp is not None else "—")

    fig = go.Figure()
    if "Net_Liq" in wliq:
        fig.add_scatter(x=wliq.index, y=wliq["Net_Liq"], name="Net Liq (W-WED)",
                        line=dict(width=2))
        fig.add_scatter(x=wliq.index, y=wliq["MA12"], name="12주 MA",
                        line=dict(dash="dot"))
    if "WRESBAL" in wliq:
        fig.add_scatter(x=wliq.index, y=wliq["WRESBAL"], name="지급준비금 WRESBAL",
                        line=dict(dash="dash"))
    fig.update_layout(height=340, margin=dict(t=30, b=10),
                      title="순유동성 vs 지급준비금 ($bn) — 두 시리즈 괴리 = 근사식 오차 점검")
    st.plotly_chart(fig, width="stretch")

    with st.expander("구성요소 (Fed 자산 / TGA / RRP)"):
        cols = [c for c in ["WALCL", "TGA", "RRPONTSYD"] if c in wliq.columns]
        st.line_chart(wliq[cols], height=260)
        st.download_button("CSV 다운로드", wliq.to_csv().encode(),
                           "liquidity_weekly.csv")

    st.divider()

    # ── §3 단기 국채발행 모듈 (FiscalData — v18 신규)
    st.subheader("🏛️ 단기 국채(T-Bill) 발행 — 시장에 돈이 풀리나, 빨리나")
    bills = fetch_bill_flows()
    if bills is None or bills.empty:
        st.warning("재무부 FiscalData 응답 실패 — 잠시 후 새로고침하거나 데이터 품질 페이지 확인")
    else:
        net_4w = float(bills["순발행"].tail(4).sum())
        rrp_chg = None
        if "RRPONTSYD" in macro:
            r = macro["RRPONTSYD"].dropna()
            if len(r) > 21:
                rrp_chg = float(r.iloc[-1] - r.iloc[-21])
        verdict, badge = bill_liquidity_matrix(net_4w, rrp, rrp_chg)
        st.markdown(f"### {badge} 판정: {verdict}")
        st.caption(f"최근 4주 순발행 {net_4w:+,.0f} $bn · RRP 4주 변화 "
                   f"{rrp_chg:+,.0f} $bn" if rrp_chg is not None
                   else f"최근 4주 순발행 {net_4w:+,.0f} $bn")

        fig2 = go.Figure()
        fig2.add_bar(x=bills.index, y=bills["순발행"], name="주간 Bill 순발행 ($bn)")
        if "RRPONTSYD" in macro:
            rr = macro["RRPONTSYD"].dropna().resample("W-WED").last()
            rr = rr[rr.index >= bills.index[0]]
            fig2.add_scatter(x=rr.index, y=rr, name="RRP 잔고 ($bn)",
                             yaxis="y2", line=dict(width=2))
        fig2.update_layout(
            height=340, margin=dict(t=30, b=10),
            yaxis=dict(title="순발행 $bn"),
            yaxis2=dict(title="RRP $bn", overlaying="y", side="right"),
            title="Bill 순발행 vs RRP — 'RRP 바닥 + 순발행↑'이 위험 조합")
        st.plotly_chart(fig2, width="stretch")
        st.caption("QRA(분기 국채발행계획) 발표: 매년 2/5/8/11월 초 — 발행 구성(Bill↔쿠폰) "
                   "변화가 유동성·장기금리에 직접 영향")

    auc = fetch_auctions()
    if auc is not None and not auc.empty:
        st.subheader("Bill 경매 응찰배율 (bid-to-cover)")
        b2c = auc.set_index("auction_date")["bid_to_cover_ratio"].dropna()
        if not b2c.empty:
            roll = b2c.rolling(10).mean()
            st.line_chart(pd.DataFrame({"b2c": b2c, "10회 평균": roll}), height=220)
            st.caption("추세 하락 = 단기물 수요 약화 → 단기금리 상방 압력")

    # ── TGA 일간 (DTS가 FRED 주간보다 빠름)
    tga_d = fetch_tga_daily()
    if tga_d is not None and not tga_d.empty:
        st.subheader("TGA 일간 잔고 (재무부 DTS — FRED보다 신속)")
        st.line_chart(tga_d.tail(250), height=220)
        st.caption("세수기(4월/6월/9월/1월 중순) 급증 = 단기 유동성 흡수 이벤트")
