# ui/page_dashboard.py
import pandas as pd
import streamlit as st

from core.utils import get_val, fmt_pct
from data.fred import buffett_indicator
from data.market import fetch_fear_greed
from agent.triggers import evaluate_triggers
from ui.common import get_state, get_geo, index_snapshot


def render():
    st.title("📊 대시보드")
    state = get_state()
    reg, macro, liq = state["regime"], state["macro"], state["liq"]
    geo_score, geo_label, _ = get_geo()

    # ── 트리거 배지 (§8-3)
    prev_vix = st.session_state.get("_prev_vix")
    snap = {"regime": reg["label"],
            "prev_regime": st.session_state.get("_prev_regime_for_trigger"),
            "vix": state["vix"], "prev_vix": prev_vix,
            "liq_z": liq["z"], "hy_1m_chg": get_val(macro, "HY_1M_Chg"),
            "my_var95": st.session_state.get("_my_var95"),
            "max_asset": st.session_state.get("max_asset"),
            "my_weights": st.session_state.get("_my_weights")}
    st.session_state["_prev_vix"] = state["vix"]
    fired = evaluate_triggers(snap)
    st.session_state["_fired_triggers"] = fired
    if fired:
        for f in fired:
            (st.error if f["level"] == "alert" else st.warning)(
                f"🔔 **{f['name']}** — {f['msg']}")
    else:
        st.success("🔕 발동된 트리거 없음")

    # ── 핵심 지표
    c1, c2, c3, c4 = st.columns(4)
    vix_series = state["close"]["^VIX"].dropna() if "^VIX" in state["close"].columns else None
    fg = fetch_fear_greed(vix=state["vix"], vix_series=vix_series)
    if fg:
        src = fg.get("source", "")
        c1.metric("공포탐욕지수", f"{fg['score']:.0f} ({fg['rating']})",
                  help=f"출처: {src}")
        if src.startswith("VIX"):
            c1.caption(f"⚠️ CNN/대안 API 차단 → VIX 퍼센타일 자체 계산 (참고용)")
    else:
        c1.metric("공포탐욕지수", "—")
    c2.metric("VIX", f"{state['vix']:.1f}" if state["vix"] else "—")
    c3.metric("레짐", reg["display"], f"점수 {reg['score']:+.1f}")
    c4.metric("지정학 리스크", f"{geo_label} ({geo_score})")

    if reg.get("hysteresis_active"):
        st.caption(f"ℹ️ 히스테리시스 작동 중: 원점수 기준은 `{reg['raw_label']}`이지만 "
                   f"전환 마진(±1.5) 미달로 `{reg['label']}` 유지")

    # ── 폭락 리스크 요약 (상세는 리스크 레이더 페이지)
    from engine.risk_radar import crash_risk, stagflation_score
    bf_z = None
    bf_tmp = buffett_indicator()
    if bf_tmp is not None and not bf_tmp.empty:
        bf_z = float(bf_tmp["z"].iloc[-1])
    spy_c = state["close"]["SPY"] if "SPY" in state["close"].columns else None
    stag = stagflation_score(macro)
    crash = crash_risk(macro, state["vix"], spy_c, bf_z,
                       stag["score"] if stag["score"] is not None else None)
    cc = st.columns(4)
    for col, h in zip(cc[:3], ["1주", "1달", "1년"]):
        r = crash.get(h, {})
        if r.get("score") is not None:
            icon = "🟢" if r["score"] < 34 else "🟡" if r["score"] < 67 else "🔴"
            col.metric(f"폭락리스크 {h}", f"{icon} {r['label']}",
                       f"{r['on']}/{r['total']} 충족")
    if stag["score"] is not None:
        sicon = "🟢" if stag["score"] < 35 else "🟡" if stag["score"] < 60 else "🔴"
        cc[3].metric("스태그플레이션", f"{sicon} {stag['label']}", f"{stag['score']}")
    st.caption("↑ 폭락 리스크는 '역사적 선행조건 충족도'이며 확률 예측이 아닙니다. "
               "상세는 좌측 **리스크 레이더** 페이지 참고.")

    # ── 레짐 7축 테이블
    st.subheader("매크로 레짐 — 7축 분해")
    axdf = pd.DataFrame(reg["axes"]).rename(
        columns={"axis": "축", "state": "상태", "score": "점수", "detail": "상세"})
    st.dataframe(axdf, width="stretch", hide_index=True)

    # ── 버핏지표 (v18: 장기평균 Z-score 병기, §1-5)
    st.subheader("버핏지표 (비금융기업 시총/GDP)")
    bf = buffett_indicator()
    if bf is not None and not bf.empty:
        last = bf.iloc[-1]
        b1, b2 = st.columns(2)
        b1.metric("비율", f"{last['ratio']:.2f}", f"장기평균 대비 z = {last['z']:+.2f}")
        b2.line_chart(bf["ratio"], height=180)
        st.caption("⚠️ NCBEILQ027S(비금융기업)는 윌셔 전체시장 대비 약 20% 작게 산출됨. "
                   "절대 구간보다 z-score(장기평균 대비 괴리)로 해석할 것.")
    else:
        st.info("버핏지표 데이터 로드 실패")

    # ── 주요 지수
    st.subheader("주요 지수")
    idx = index_snapshot()
    if not idx.empty:
        idx_show = idx.copy()
        idx_show["1일"] = idx_show["1일"].map(lambda x: fmt_pct(x, 2))
        idx_show["1개월"] = idx_show["1개월"].map(lambda x: fmt_pct(x, 1))
        st.dataframe(idx_show, width="stretch", hide_index=True)
