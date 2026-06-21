# ui/page_risk.py — 리스크 레이더 (연준·금리·스태그플레이션·폭락 게이지)  v18.1
import plotly.graph_objects as go
import streamlit as st

from core.utils import fmt_num, get_val
from data.fred import buffett_indicator
from engine.risk_radar import (stagflation_score, fed_balance_sheet, rate_path,
                               crash_risk, crash_summary)
from ui.common import get_state


def _gauge(score, title):
    color = "#2ecc71" if score < 34 else "#f1c40f" if score < 67 else "#e74c3c"
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        title={"text": title, "font": {"size": 14}},
        number={"font": {"size": 28}},
        gauge={"axis": {"range": [0, 100]},
               "bar": {"color": color},
               "steps": [{"range": [0, 34], "color": "rgba(46,204,113,0.15)"},
                         {"range": [34, 67], "color": "rgba(241,196,15,0.15)"},
                         {"range": [67, 100], "color": "rgba(231,76,60,0.15)"}]}))
    fig.update_layout(height=200, margin=dict(t=40, b=10, l=20, r=20))
    return fig


def render():
    st.title("⚠️ 리스크 레이더")
    st.caption("연준 대차대조표 · 금리 경로 · 스태그플레이션 · 폭락 선행조건을 종합 점검합니다. "
               "폭락 게이지는 '확률'이 아니라 '역사적 선행조건 충족도'입니다.")

    state = get_state()
    macro, vix = state["macro"], state["vix"]
    spy = state["close"]["SPY"] if "SPY" in state["close"].columns else None
    bf = buffett_indicator()
    bf_z = float(bf["z"].iloc[-1]) if bf is not None and not bf.empty else None

    # ── 스태그플레이션
    stag = stagflation_score(macro)
    crash = crash_risk(macro, vix, spy, bf_z,
                       stag["score"] if stag["score"] is not None else None)

    # ════ 폭락 리스크 게이지 (3 시간축) ════
    st.subheader("📉 폭락 리스크 게이지")
    st.caption(f"종합: {crash_summary(crash)}")
    cols = st.columns(3)
    for col, h in zip(cols, ["1주", "1달", "1년"]):
        r = crash[h]
        with col:
            if r["score"] is None:
                st.info(f"**{h}** — 데이터 부족")
                continue
            st.plotly_chart(_gauge(r["score"],
                                   f"{h} 이내 ({r['on']}/{r['total']} 충족)"),
                            width="stretch")
            for f in r["flags"]:
                icon = "🔴" if f["on"] else "⚪"
                st.write(f"{icon} {f['label']} `{f['val']}`")

    st.warning("⚠️ 이 게이지는 미래 예측이 아닙니다. 과거 폭락에 선행했던 조건들이 "
               "현재 몇 개 켜져 있는지를 보여줄 뿐이며, 조건이 모두 켜져도 폭락하지 "
               "않을 수 있고 그 반대도 가능합니다. 포지션 점검용 참고 지표로만 쓰세요.")

    st.divider()

    # ════ 스태그플레이션 ════
    st.subheader("🌡️ 스태그플레이션 리스크")
    if stag["score"] is None:
        st.info("데이터 부족 — CPI/산업생산/실업률 시리즈 확인 필요")
    else:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.plotly_chart(_gauge(stag["score"], f"종합 ({stag['label']})"),
                            width="stretch")
        with c2:
            st.markdown("**구성 요소**")
            for name, d in stag["detail"].items():
                bar = "█" * int(d["score"] * 10) + "░" * (10 - int(d["score"] * 10))
                st.write(f"- **{name}**: `{bar}` {d['note']}")
            if stag.get("combo", 0) > 0.3:
                st.error("인플레이션과 성장둔화가 동시에 높습니다 — "
                         "전형적 스태그플레이션 조합. 실물자산(에너지·금)·"
                         "단기채 비중 점검 권장.")
            else:
                st.caption("인플레이션·성장·고용 중 일부만 악화 — 아직 본격 "
                           "스태그플레이션 조합은 아님.")

    st.divider()

    # ════ 연준 대차대조표 ════
    st.subheader("🏦 연준 대차대조표")
    fbs = fed_balance_sheet(macro)
    if not fbs:
        st.info("대차대조표 데이터 로드 실패")
    else:
        m = st.columns(4)
        m[0].metric("총자산", f"{fmt_num(fbs.get('총자산'), 0)} $bn",
                    f"13주 {fbs.get('13주 변화', 0):+,.0f}")
        m[1].metric("QT/QE", fbs.get("QT 진행", "—"))
        if fbs.get("보유 국채"):
            m[2].metric("보유 국채", f"{fmt_num(fbs['보유 국채'], 0)} $bn")
        if fbs.get("보유 MBS"):
            m[3].metric("보유 MBS", f"{fmt_num(fbs['보유 MBS'], 0)} $bn")
        if fbs.get("지준/총자산"):
            st.caption(f"지급준비금/총자산 {fbs['지준/총자산']}% — "
                       "낮아질수록 유동성 완충 여력 축소 (2019년 레포 발작 수준 경계)")
        # 대차대조표 추이
        walcl = macro.get("WALCL")
        if walcl is not None:
            w = walcl.dropna()
            fig = go.Figure()
            fig.add_scatter(x=w.index, y=w, name="총자산", line=dict(width=2))
            for col, nm in [("TREAST", "국채"), ("WSHOMCB", "MBS")]:
                s = macro.get(col)
                if s is not None and len(s.dropna()):
                    fig.add_scatter(x=s.dropna().index, y=s.dropna(), name=nm,
                                    line=dict(dash="dot"))
            fig.update_layout(height=300, margin=dict(t=20, b=10),
                              title="연준 자산 추이 ($bn)",
                              legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig, width="stretch")

    st.divider()

    # ════ 금리 경로 (점도표 근사) ════
    st.subheader("📈 금리 경로 (시장 기대 기반)")
    st.caption("공식 점도표(FOMC SEP)는 분기 PDF로만 공개되어 API가 없습니다. "
               "대신 현재 정책금리 + 국채 커브로 '시장이 반영한' 금리 경로를 근사합니다.")
    rp = rate_path(macro)
    m = st.columns(4)
    m[0].metric("정책금리 상단", f"{fmt_num(rp.get('정책금리 상단'), 2)}%")
    m[1].metric("실효 FFR", f"{fmt_num(rp.get('실효 FFR'), 2)}%")
    m[2].metric("2년물", f"{fmt_num(rp.get('2년'), 2)}%")
    m[3].metric("시장 기대", rp.get("시장 기대", "—"),
                f"2Y-정책 {rp.get('2년-정책금리', 0):+.2f}" if rp.get("2년-정책금리") is not None else None)

    # 커브 시각화
    pts = [("3개월", rp.get("3개월")), ("2년", rp.get("2년")), ("10년", rp.get("10년"))]
    pts = [(k, v) for k, v in pts if v is not None]
    if len(pts) >= 2:
        fig = go.Figure(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts],
                                   mode="lines+markers", line=dict(width=2)))
        fig.update_layout(height=240, margin=dict(t=20, b=10),
                          title="국채 수익률 곡선", yaxis_title="%")
        st.plotly_chart(fig, width="stretch")
    if rp.get("커브 역전"):
        st.error(f"🔴 수익률 곡선 역전 — 10Y-3M {rp.get('10Y-3M', 0):+.2f}%, "
                 f"10Y-2Y {rp.get('10Y-2Y', 0):+.2f}%. 역사적으로 침체 12~18개월 "
                 "선행 신호로 알려져 있습니다(절대적 예측은 아님).")
    else:
        st.success("커브 정상 (역전 아님)")
