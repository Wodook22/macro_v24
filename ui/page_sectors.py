# ui/page_sectors.py — 섹터 로테이션 + AI 테마 모듈 (§7)
import pandas as pd
import streamlit as st

from core.config import SECTOR_ETFS, SECTOR_STOCKS, AI_BASKET
from core.utils import fmt_pct
from data.market import fetch_prices
from engine.scoring import score_assets, reason_table
from ui.common import get_state, scored_sectors


def render():
    st.title("🔄 섹터 로테이션 & AI 테마")
    state = get_state()

    # ── 섹터 스코어
    scored = scored_sectors(state)
    if scored.empty:
        st.error("섹터 데이터 부족")
        return
    etf2name = {v: k for k, v in SECTOR_ETFS.items()}
    show = scored.drop(columns=["_axes_used"], errors="ignore").round(2)
    show.insert(0, "섹터", [etf2name.get(i, i) for i in show.index])
    st.subheader("섹터 종합 스코어 (가중치 합 자동 정규화 = 1.00)")
    st.dataframe(show, width="stretch")
    st.caption(f"사용 축: {scored['_axes_used'].iloc[0]}")

    st.subheader("📋 투자 추천 이유표")
    st.dataframe(reason_table(scored, top_n=st.session_state.get("top_n", 3)),
                 width="stretch", hide_index=True)

    # ── 상위 섹터 내 종목 랭킹
    top_n = st.session_state.get("top_n", 3)
    top_secs = [etf2name.get(t, t) for t in scored.head(top_n).index]
    stocks = sorted({s for sec in top_secs for s in SECTOR_STOCKS.get(sec, [])})
    if stocks:
        st.subheader(f"상위 {top_n}개 섹터 내 종목 랭킹")
        cl, vol = fetch_prices(tuple(stocks + ["SPY"]),
                               st.session_state.get("period", "2y"))
        if not cl.empty:
            sc = score_assets(cl, vol if not vol.empty else None, bench="SPY")
            n_show = st.session_state.get("n_stocks", 8)
            st.dataframe(sc.drop(columns=["_axes_used"], errors="ignore")
                         .round(2).head(n_show), width="stretch")

    st.divider()

    # ── §7 AI 밸류체인
    st.subheader("🤖 AI 밸류체인 — 자금이 어느 단계로 이동 중인가")
    all_ai = sorted({t for v in AI_BASKET.values() for t in v})
    cl_ai, _ = fetch_prices(tuple(all_ai + ["SPY", "RSP"]), "1y")
    if cl_ai.empty:
        st.info("AI 바스켓 데이터 로드 실패")
        return

    rows = []
    for stage, members in AI_BASKET.items():
        cols = [t for t in members if t in cl_ai.columns]
        if not cols:
            continue
        eq = cl_ai[cols].pct_change().mean(axis=1)   # 등가중
        cum = (1 + eq).cumprod().dropna()
        if len(cum) < 64:
            continue
        rows.append({"단계": stage, "구성": ", ".join(cols),
                     "1M": cum.iloc[-1] / cum.iloc[-21] - 1,
                     "3M": cum.iloc[-1] / cum.iloc[-63] - 1})
    chain = pd.DataFrame(rows)
    if not chain.empty:
        chain_show = chain.copy()
        for c in ["1M", "3M"]:
            chain_show[c] = chain_show[c].map(lambda x: fmt_pct(x, 1))
        st.dataframe(chain_show, width="stretch", hide_index=True)
        best = chain.loc[chain["1M"].idxmax()]
        st.caption(f"최근 1개월 자금 집중 단계: **{best['단계']}**")

    # AI vs SPY 상대강도 + 쏠림(폭) 진단
    c1, c2 = st.columns(2)
    with c1:
        ai_cols = [t for t in all_ai if t in cl_ai.columns]
        if ai_cols and "SPY" in cl_ai.columns:
            ai_eq = (1 + cl_ai[ai_cols].pct_change().mean(axis=1)).cumprod()
            spy = (cl_ai["SPY"] / cl_ai["SPY"].dropna().iloc[0]).dropna()
            rel = (ai_eq / spy).dropna()
            st.markdown("**AI 바스켓 / SPY 상대강도**")
            st.line_chart(rel, height=220)
        else:
            st.caption("AI/SPY 데이터 부족")
    with c2:
        if {"RSP", "SPY"}.issubset(cl_ai.columns):
            breadth = (cl_ai["RSP"] / cl_ai["SPY"]).dropna()
            if len(breadth):
                st.markdown("**RSP/SPY (시장 폭)**")
                st.line_chart(breadth / breadth.iloc[0], height=220)
                st.caption("하락 지속 = 소수 대형(AI) 쏠림 심화 → 쏠림 해소 시 변동성 리스크")
