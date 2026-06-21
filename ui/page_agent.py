# ui/page_agent.py — AI 에이전트 (§8): 앱이 계산한 상태 → LLM 구조화 판단
import json

import pandas as pd
import streamlit as st

from core.config import (LLM_LIMIT, FLOW_UNIVERSE, FLOW_BENCH,
                         FLOW_RATIO_TICKERS)
from core.utils import get_val, fmt_pct
from data.market import fetch_prices
from data.crypto import fetch_stablecoin_mcap
from engine.flows import rrg_coords, rrg_table, flow_summary
from agent.llm import call_agent
from ui.common import get_state, get_geo, scored_sectors


def _build_context(state: dict) -> str:
    """LLM에 전달할 컨텍스트 마크다운 — 앱이 계산한 수치만 (할루시네이션 방지)"""
    reg, liq, macro = state["regime"], state["liq"], state["macro"]
    geo_score, geo_label, _ = get_geo()

    lines = ["## 레짐"]
    lines.append(f"- 종합점수 {reg['score']:+.2f} → **{reg['display']}** "
                 f"(원시 라벨 {reg['raw_label']}, 히스테리시스 "
                 f"{'적용' if reg['hysteresis_active'] else '미적용'})")
    for a in reg["axes"]:
        lines.append(f"  - {a['axis']}: {a['detail']} ({a['score']:+.1f})")

    lines.append("\n## 유동성")
    if liq["z"] is not None:
        acc = f"{liq['accel']:+.3f}" if liq["accel"] is not None else "—"
        lines.append(f"- 상태 {liq['state']} / 1M z-score "
                     f"{liq['z']:.2f} / 가속도 {acc}")
    else:
        lines.append("- 데이터 부족")
    for col, label in [("Net_Liq", "Net Liq ($bn)"), ("RRP", "역레포 ($bn)"),
                       ("TGA", "TGA ($bn)")]:
        v = get_val(macro, col)
        if v is not None:
            lines.append(f"- {label}: {v:,.0f}")

    # 자금흐름 요약
    try:
        tickers = tuple(set(list(FLOW_UNIVERSE.values()) + [FLOW_BENCH]
                            + FLOW_RATIO_TICKERS))
        close, _ = fetch_prices(tickers, "1y")
        rename = {v: k for k, v in FLOW_UNIVERSE.items()}
        cl = close.rename(columns=rename)
        cols = [c for c in list(FLOW_UNIVERSE.keys()) + [FLOW_BENCH]
                if c in cl.columns]
        table = rrg_table(rrg_coords(cl[cols], FLOW_BENCH))
        stable = fetch_stablecoin_mcap()
        chg = (float(stable.iloc[-1] - stable.iloc[-30])
               if stable is not None and len(stable) > 30 else None)
        lines.append("\n## 자금흐름")
        lines.append(f"- {flow_summary(table, chg)}")
    except Exception:                            # noqa: BLE001
        pass

    lines.append("\n## 지정학")
    lines.append(f"- 자동 점수 {geo_score} ({geo_label})")

    # 리스크 레이더 (스태그플레이션 + 폭락 게이지)
    try:
        from data.fred import buffett_indicator
        from engine.risk_radar import stagflation_score, crash_risk, rate_path
        bf = buffett_indicator()
        bf_z = float(bf["z"].iloc[-1]) if bf is not None and not bf.empty else None
        spy_c = state["close"]["SPY"] if "SPY" in state["close"].columns else None
        stag = stagflation_score(macro)
        crash = crash_risk(macro, state["vix"], spy_c, bf_z,
                           stag["score"] if stag["score"] is not None else None)
        lines.append("\n## 리스크 레이더")
        if stag["score"] is not None:
            lines.append(f"- 스태그플레이션 {stag['score']} ({stag['label']})")
        for h in ["1주", "1달", "1년"]:
            r = crash.get(h, {})
            if r.get("score") is not None:
                on_flags = [f["label"] for f in r["flags"] if f["on"]]
                lines.append(f"- 폭락리스크 {h}: {r['label']} ({r['on']}/{r['total']})"
                             + (f" — {', '.join(on_flags)}" if on_flags else ""))
        rp = rate_path(macro)
        if rp.get("커브 역전"):
            lines.append(f"- 수익률곡선 역전 (10Y-3M {rp.get('10Y-3M')}%)")
        if rp.get("시장 기대"):
            lines.append(f"- 금리 시장기대: {rp['시장 기대']}")
    except Exception:                            # noqa: BLE001
        pass

    # 섹터 스코어 상위
    try:
        sc = scored_sectors(state).head(5)
        lines.append("\n## 섹터 스코어 Top 5")
        for t, row in sc.iterrows():
            lines.append(f"- {t}: {row['score']:.2f}")
    except Exception:                            # noqa: BLE001
        pass

    # 내 포트폴리오
    mw = st.session_state.get("_my_weights")
    if mw:
        lines.append("\n## 내 포트폴리오 (비중)")
        for a, w in sorted(mw.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {a}: {w*100:.1f}%")
        var = st.session_state.get("_my_var95")
        if var is not None:
            lines.append(f"- 일간 VaR95: {var*100:.2f}%")
    else:
        lines.append("\n## 내 포트폴리오\n- 미입력 (포트폴리오 페이지에서 입력)")

    # 발동 트리거
    fired = st.session_state.get("_fired_triggers") or []
    if fired:
        lines.append("\n## 발동 트리거")
        for f in fired:
            lines.append(f"- [{f['level']}] {f['name']}: {f['msg']}")

    return "\n".join(lines)


def render():
    st.title("🤖 AI 에이전트")
    st.caption("앱이 계산한 레짐·유동성·자금흐름·내 포트폴리오를 근거로 "
               "LLM이 구조화된 리밸런싱 시나리오를 제안합니다. "
               "투자 '지시'가 아닌 근거 기반 '제안'입니다.")

    ak = st.session_state.get("anthropic_key") or ""
    gk = st.session_state.get("gemini_key") or ""
    if not (ak or gk):
        st.warning("사이드바에 Anthropic 또는 Gemini API 키를 입력하세요. "
                   "(Streamlit Secrets의 ANTHROPIC_API_KEY / GEMINI_API_KEY도 사용 가능)")

    used = st.session_state.get("_llm_calls", 0)
    st.progress(min(used / LLM_LIMIT, 1.0),
                text=f"세션 호출 {used}/{LLM_LIMIT}")

    state = get_state()
    ctx = _build_context(state)
    with st.expander("LLM에 전달되는 컨텍스트 (검증용)"):
        st.code(ctx, language="markdown")

    if st.button("🧠 분석 실행", type="primary",
                 disabled=used >= LLM_LIMIT or not (ak or gk)):
        with st.spinner("LLM 분석 중..."):
            parsed, raw, provider = call_agent(ctx, ak, gk)
        st.session_state["_llm_calls"] = used + 1
        st.session_state["_agent_result"] = (parsed, raw, provider)

    if used >= LLM_LIMIT:
        st.error(f"세션 호출 한도({LLM_LIMIT}회) 도달 — 새로고침 시 초기화")

    res = st.session_state.get("_agent_result")
    if not res:
        return
    parsed, raw, provider = res
    st.caption(f"제공자: {provider}")

    if parsed is None:
        st.error("JSON 파싱 실패 — 원문을 확인하세요")
        st.code(raw)
        return

    # ── 시장 판단
    mv = parsed.get("market_view", {})
    c1, c2 = st.columns([1, 2])
    c1.metric("에이전트 레짐 판단", mv.get("regime", "—"),
              f"확신도 {mv.get('confidence', 0):.0%}")
    if mv.get("key_drivers"):
        c2.info("**핵심 근거** — " + " · ".join(mv["key_drivers"]))

    # ── 자금흐름 판단
    lf = parsed.get("liquidity_flow", {})
    if lf:
        st.markdown(f"**유동성 이동**: {', '.join(lf.get('from', []) or ['—'])} "
                    f"→ {', '.join(lf.get('to', []) or ['—'])}")
        if lf.get("evidence"):
            st.caption("근거: " + " / ".join(lf["evidence"]))

    # ── 액션 테이블
    actions = parsed.get("portfolio_actions", [])
    if actions:
        st.subheader("제안 액션")
        urg_icon = {"now": "🔴 즉시", "this_week": "🟡 이번 주",
                    "watch": "👀 관찰"}
        rows = []
        for a in actions:
            rows.append({
                "자산": a.get("asset", ""),
                "현재": fmt_pct(a.get("current_w", 0)),
                "제안": fmt_pct(a.get("suggested_w", 0)),
                "긴급도": urg_icon.get(a.get("urgency", ""), a.get("urgency", "")),
                "근거": a.get("rationale", ""),
                "근거 지표": ", ".join(a.get("evidence_ids", []))})
        st.dataframe(pd.DataFrame(rows), width="stretch",
                     hide_index=True)

    # ── 리스크/무효화 조건
    if parsed.get("risk_flags"):
        for r in parsed["risk_flags"]:
            st.warning(f"⚠️ {r}")
    if parsed.get("invalidation"):
        st.error(f"**시나리오 무효화 조건** — {parsed['invalidation']}")

    with st.expander("원본 JSON"):
        st.code(json.dumps(parsed, ensure_ascii=False, indent=2),
                language="json")
