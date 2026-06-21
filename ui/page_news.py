# ui/page_news.py — 지정학/뉴스 리스크 자동 점수 (§4)
import plotly.graph_objects as go
import streamlit as st

from core.config import NEWS_CATEGORIES
from data.news import gdelt_category_score, rss_headlines, total_geo_score


def render():
    st.title("📰 뉴스/지정학 리스크")
    st.caption("GDELT 전세계 뉴스 볼륨 기반 자동 점수 — "
               "최근 7일 기사비율 ÷ 직전 90일 평균 (ratio 1.0 = 평상시 50점)")

    # ── 카테고리별 점수 수집
    scores, details = {}, {}
    gdelt_fails = 0
    with st.spinner("GDELT 뉴스 볼륨 분석 중..."):
        for cat in NEWS_CATEGORIES:
            r = gdelt_category_score(cat)
            scores[cat] = r["score"] if r else None
            details[cat] = r
            if r is None:
                gdelt_fails += 1

    if gdelt_fails > 0:
        st.info(
            f"ℹ️ GDELT API {gdelt_fails}개 카테고리 일시 실패 (레이트리밋 429). "
            "6시간 캐시 적용 중 — 다음 접속 시 자동 복구됩니다. "
            "현재는 가용 카테고리로 점수를 계산하며, RSS 헤드라인은 정상 표시됩니다.",
            icon="ℹ️"
        )

    total, label = total_geo_score(scores)
    override = st.session_state.get("geo_override", "자동")

    c1, c2 = st.columns([1, 3])
    icon = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}[label]
    c1.metric("종합 지정학 점수", f"{total} {icon} {label}")
    if override != "자동":
        c2.warning(f"사이드바에서 수동 오버라이드 **{override}** 적용 중 — "
                   "현금비중 계산은 오버라이드 값을 사용합니다. "
                   "자동 점수로 되돌리려면 사이드바에서 '자동'을 선택하세요.")
    else:
        c2.info("자동 점수가 현금비중 계산에 반영됩니다. "
                "전쟁/분쟁 카테고리는 1.5배 가중.")

    # ── 카테고리 카드
    cols = st.columns(len(NEWS_CATEGORIES))
    for col, (cat, sc) in zip(cols, scores.items()):
        d = details[cat]
        if sc is None:
            col.metric(cat, "—", help="GDELT 수집 실패")
        else:
            col.metric(cat, f"{sc}", f"비율 {d['ratio']:.2f}x",
                       delta_color="inverse")

    # ── 뉴스 볼륨 추이 차트
    fig = go.Figure()
    palette = ["#e74c3c", "#f1c40f", "#4da6ff", "#9b59b6"]
    for (cat, d), color in zip(details.items(), palette):
        if d is None:
            continue
        s = d["series"]
        fig.add_trace(go.Scatter(x=s.index, y=s, name=cat,
                                 line=dict(color=color, width=1.5)))
    if fig.data:
        fig.update_layout(height=320, margin=dict(t=30, b=10),
                          yaxis_title="전세계 뉴스 대비 기사비율 (%)",
                          legend=dict(orientation="h", y=1.12),
                          hovermode="x unified")
        st.plotly_chart(fig, width="stretch")

    # ── 카테고리별 헤드라인
    st.subheader("주요 헤드라인 (Google News RSS)")
    tabs = st.tabs(list(NEWS_CATEGORIES.keys()))
    for tab, cat in zip(tabs, NEWS_CATEGORIES):
        with tab:
            items = rss_headlines(cat)
            if not items:
                st.caption("헤드라인 수집 실패")
            for it in items:
                st.markdown(f"- [{it['title']}]({it['link']})  "
                            f"<span style='color:gray;font-size:0.8em'>"
                            f"{it['published'][:16]}</span>",
                            unsafe_allow_html=True)

    st.caption("⚠️ 키워드 볼륨 기반 점수는 보도량 급증을 감지할 뿐, "
               "사건의 시장 영향 방향을 판단하지 않습니다. "
               "판단은 레짐/유동성 축과 함께 종합하세요.")
