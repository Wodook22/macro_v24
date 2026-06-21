# ui/page_timing.py — 진입 타이밍 / 조정 분할매수 (v18.2)
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import TIMING_INDEX, TIMING_MEGACAP, TIMING_DEFAULTS
from core.utils import fmt_pct
from data.market import fetch_prices, fetch_fear_greed
from data.fred import buffett_indicator
from engine.risk_radar import crash_risk, stagflation_score
from engine.timing import (find_support_resistance, confluence_score, dca_plan,
                           crash_circuit_breaker, long_term_bottom, backtest_dca)
from ui.common import get_state


def _sr_chart(close, sr, fg_series=None, title=""):
    s = close.dropna().tail(252)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.index, y=s, name="가격",
                             line=dict(color="#4da6ff", width=1.8)))
    for lv, t in sr.get("support", [])[:3]:
        fig.add_hline(y=lv, line_dash="dash", line_color="#2ecc71",
                      annotation_text=f"지지 {lv:.0f} ({t}회)",
                      annotation_position="right")
    for lv, t in sr.get("resistance", [])[:3]:
        fig.add_hline(y=lv, line_dash="dot", line_color="#e74c3c",
                      annotation_text=f"저항 {lv:.0f}",
                      annotation_position="right")
    fig.update_layout(height=380, margin=dict(t=30, b=10), title=title,
                      hovermode="x unified", showlegend=False)
    return fig


def render():
    st.title("🎯 진입 타이밍 — 조정 분할매수")
    st.caption("우상향 가정 하에 '언제 담을지' 타이밍을 잡습니다. 공포탐욕 + 지지선 + "
               "라운드넘버 + 과매도가 겹치는(합류) 구간을 포착하되, 폭락장 차단기가 "
               "'떨어지는 칼날'을 막습니다. 데이터는 접속 시 자동 갱신됩니다.")

    state = get_state()
    macro, vix = state["macro"], state["vix"]

    # ── 공통: 폭락장 차단기 상태 (모든 진입 판단의 게이트)
    spy_c = state["close"]["SPY"] if "SPY" in state["close"].columns else None
    bf = buffett_indicator()
    bf_z = float(bf["z"].iloc[-1]) if bf is not None and not bf.empty else None
    stag = stagflation_score(macro)
    stag_score = stag["score"] if stag["score"] is not None else None
    crash = crash_risk(macro, vix, spy_c, bf_z, stag_score)
    breaker = crash_circuit_breaker(macro, crash, stag_score)

    # 차단기 배너
    if breaker["blocked"]:
        st.error(f"{breaker['msg']}  \n경고 {breaker['n_warnings']}개: "
                 + ", ".join(w["label"] for w in breaker["warnings"]))
    elif breaker["state"] == "경계":
        st.warning(f"{breaker['msg']}  \n경고 {breaker['n_warnings']}개: "
                   + ", ".join(w["label"] for w in breaker["warnings"]))
    else:
        st.success(breaker["msg"])

    fg = fetch_fear_greed(vix=vix,
                          vix_series=state["close"]["^VIX"].dropna()
                          if "^VIX" in state["close"].columns else None)
    fg_val = fg["score"] if fg else None

    # ── 대상 선택
    target_type = st.radio("분석 대상", ["지수 ETF", "시총 상위 개별주"],
                           horizontal=True)
    universe = TIMING_INDEX if target_type == "지수 ETF" else TIMING_MEGACAP
    pick = st.selectbox("종목", list(universe.keys()))
    ticker = universe[pick]

    aggression = st.session_state.get("timing_aggression",
                                      TIMING_DEFAULTS["aggression"])

    close_df, _ = fetch_prices(tuple(list(universe.values())), "3y")
    if close_df.empty or ticker not in close_df.columns:
        st.error("가격 데이터 로드 실패")
        return
    s = close_df[ticker].dropna()

    # ── 합류 분석
    sr = find_support_resistance(s)
    conf = confluence_score(s, fg_val, sr)
    plan = dca_plan(conf, fg_val, blocked=breaker["blocked"],
                    aggression=aggression,
                    max_rounds=st.session_state.get("timing_max_rounds",
                                                    TIMING_DEFAULTS["max_rounds"]),
                    ammo_per_round=TIMING_DEFAULTS["ammo_per_round"])

    # ── 행동 제안 카드
    c1, c2, c3 = st.columns([1.2, 1, 1])
    c1.metric("매수 합류 점수", f"{conf['score']}/100",
              plan["action"])
    c2.metric("공포탐욕", f"{fg_val:.0f}" if fg_val is not None else "—",
              fg["rating"] if fg else None)
    c3.metric("제안 트랜치", fmt_pct(plan["tranche"]) if plan["tranche"] else "0%",
              f"현재가 {conf['price']:.1f}" if conf["price"] else None)
    st.info(f"**제안** — {plan['reason']}")

    if conf["signals"]:
        st.markdown("**합류 신호 분해**")
        sig_df = pd.DataFrame(conf["signals"], columns=["신호", "값", "점수"])
        st.dataframe(sig_df, width="stretch", hide_index=True)

    # ── 지지/저항 차트
    st.plotly_chart(_sr_chart(s, sr, title=f"{pick} — 지지/저항 (최근 1년)"),
                    width="stretch")
    if conf.get("near_support"):
        lv, t = conf["near_support"]
        st.caption(f"📍 현재가가 지지선 {lv:.0f}({t}회 터치)에 근접. "
                   "단, 지지선은 '반등 보장'이 아니라 '깨지면 가설 무효'의 기준입니다. "
                   f"이탈 시(-{TIMING_DEFAULTS['support_tol']*100:.0f}%) 손절/관망 전환 고려.")

    st.divider()

    # ── 폭락장 바닥 포착 (차단 모드에서 강조)
    st.subheader("🪂 장기 바닥 포착 (폭락장 한정)")
    if breaker["blocked"]:
        st.caption("차단기 작동 중 — 조정매수 대신 아래 장기지지선에서만 분할 진입을 고려하세요.")
    bottom = long_term_bottom(s, fg_val)
    if bottom["levels"]:
        bdf = pd.DataFrame(bottom["levels"], columns=["기준", "가격", "현재가대비%"])
        st.dataframe(bdf, width="stretch", hide_index=True)
        st.caption(bottom["note"])
    else:
        st.caption("장기지지선 데이터 부족 (3년+ 데이터 필요)")

    st.divider()

    # ── 백테스트
    st.subheader("📊 과거 공포구간 진입 성과 검증")
    bt_years = st.slider("백테스트 기간 (년)", 1, 3, 2, key="timing_bt_years")
    if st.button("백테스트 실행", key="timing_bt_btn"):
        with st.spinner("시뮬레이션 중..."):
            # 공포탐욕 프록시: 60일 고점 대비 낙폭 → 0~100
            dd = s / s.rolling(60).max() - 1
            fg_proxy = (50 + dd * 400).clip(5, 95).fillna(50)
            start = (pd.Timestamp.today() - pd.DateOffset(years=bt_years)) \
                .strftime("%Y-%m-%d")
            res = backtest_dca(s, fg_proxy, start=start, aggression=aggression)
        if res is None:
            st.error("기간이 너무 짧습니다")
        else:
            st.caption(res["note"])
            m = st.columns(3)
            m[0].metric("🎯 공포 분할매수", fmt_pct(res["strategy_return"]))
            m[1].metric("일괄매수", fmt_pct(res["lump_return"]))
            m[2].metric("매월 정액적립", fmt_pct(res["fixed_dca_return"]))
            if res["strategy_return"] > res["lump_return"]:
                st.success("✅ 이 구간에선 공포 타이밍 매수가 일괄매수를 이겼습니다 "
                           "(변동성 큰 장에서 유리).")
            else:
                st.info("ℹ️ 이 구간에선 일괄매수가 더 나았습니다. 강한 상승장에선 "
                        "보통 일찍 다 넣는 게 유리합니다 — 타이밍 전략은 변동성 큰 "
                        "장에서 빛납니다.")
            st.caption(f"사용 회차 {res['rounds_used']} · "
                       f"미투입 현금 {fmt_pct(res['cash_unused'])}")
            if not res["buys"].empty:
                with st.expander("매수 시점 상세"):
                    st.dataframe(res["buys"], width="stretch", hide_index=True)

    st.warning("⚠️ 이 도구는 '우상향 가정'에 기반합니다. 그 가정이 깨지는 국면(긴 약세장)은 "
               "폭락장 차단기가 감지하지만 완벽하지 않습니다. 탄약 상한·회차 제한을 반드시 "
               "지키고, 한 번에 모든 자금을 투입하지 마세요. 본 분석은 투자 조언이 아닙니다.")
