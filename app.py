# app.py — Macro Quant Terminal v18 진입점
# st.navigation 멀티페이지: 선택한 페이지만 실행 (v17 st.tabs 13개 전체실행 문제 해결)
import streamlit as st

from core.config import DEFAULT_SCORE_W
from data.fred import read_secret

st.set_page_config(page_title="Macro Quant Terminal v18",
                   page_icon="🌊", layout="wide",
                   initial_sidebar_state="expanded")


# ──────────────────────────────────────────────
# 공용 사이드바 — 모든 페이지가 session_state로 읽음
def sidebar():
    with st.sidebar:
        st.markdown("## 🌊 Macro Quant v18")

        st.markdown("#### 공통 설정")
        st.selectbox("가격 데이터 기간", ["1y", "2y", "3y", "5y"],
                     index=1, key="period")
        st.slider("상위 섹터 수 (Top N)", 1, 6, 3, key="top_n")
        st.slider("섹터당 종목 수", 1, 6, 3, key="n_stocks")

        st.markdown("#### 포트폴리오 제약")
        st.slider("자산별 최대비중", 0.10, 1.00, 0.30, 0.05, key="max_asset")
        st.slider("섹터별 최대비중", 0.20, 1.00, 0.50, 0.05, key="max_sector")
        st.number_input("거래비용 (bp, 왕복)", 0.0, 50.0, 5.0, 1.0,
                        key="cost_bps")
        st.number_input("무위험수익률 (연, %)", 0.0, 10.0, 4.0, 0.25,
                        key="rf_pct")
        st.session_state["rf"] = st.session_state["rf_pct"] / 100.0

        st.markdown("#### 지정학 리스크")
        st.selectbox("지정학 판단", ["자동", "Low", "Medium", "High"],
                     index=0, key="geo_override",
                     help="'자동'은 GDELT 뉴스 볼륨 기반 점수를 사용합니다")

        with st.expander("⚖️ 스코어 가중치 (자동 정규화)"):
            w = {}
            labels = {"rs_1m": "상대강도 1M", "rs_3m": "상대강도 3M",
                      "volume": "거래량", "trend": "추세(MA)",
                      "low_vol": "저변동성", "drawdown": "낙폭",
                      "macro_fit": "레짐 적합", "valuation": "밸류에이션"}
            for k, default in DEFAULT_SCORE_W.items():
                w[k] = st.slider(labels[k], 0.0, 0.5, float(default), 0.01,
                                 key=f"w_{k}")
            tot = sum(w.values())
            st.caption(f"합계 {tot:.2f} → 1.00으로 자동 정규화")
            st.session_state["score_weights"] = w

        with st.expander("🎯 진입 타이밍 설정"):
            st.selectbox("진입 공격성", ["공격적", "균형", "보수적"],
                         index=0, key="timing_aggression",
                         help="공격적: 합류점수 30+ 진입 / 균형: 45+ / 보수적: 60+")
            st.slider("최대 분할 회차", 2, 10, 5, key="timing_max_rounds",
                      help="마틴게일 방지 — 탄약을 이 회차 안에서만 소진")

        with st.expander("🔑 API 키"):
            st.text_input("Anthropic API Key", type="password",
                          value=read_secret("ANTHROPIC_API_KEY"),
                          key="anthropic_key")
            st.text_input("Gemini API Key", type="password",
                          value=read_secret("GEMINI_API_KEY"),
                          key="gemini_key")
            st.caption("FRED 키는 Secrets의 FRED_API_KEY 사용 "
                       "(없으면 CSV fallback)")

        st.divider()
        st.caption("v18.0 · 데이터 출처: FRED · 미 재무부 FiscalData · "
                   "yfinance · CoinGecko · GDELT · CNN F&G\n\n"
                   "본 앱은 정보 제공 목적이며 투자 자문이 아닙니다.")


def main():
    sidebar()

    from ui import (page_dashboard, page_liquidity, page_flows, page_sectors,
                    page_portfolio, page_backtest, page_news, page_agent,
                    page_quality, page_risk, page_timing)

    pages = {
        "분석": [
            st.Page(page_dashboard.render, title="대시보드", icon="📊",
                    url_path="dashboard", default=True),
            st.Page(page_liquidity.render, title="유동성·재정", icon="💧",
                    url_path="liquidity"),
            st.Page(page_flows.render, title="자금흐름", icon="🔀",
                    url_path="flows"),
            st.Page(page_sectors.render, title="섹터·AI 테마", icon="🏭",
                    url_path="sectors"),
            st.Page(page_news.render, title="뉴스·지정학", icon="📰",
                    url_path="news"),
            st.Page(page_risk.render, title="리스크 레이더", icon="⚠️",
                    url_path="risk"),
        ],
        "실행": [
            st.Page(page_portfolio.render, title="포트폴리오", icon="💼",
                    url_path="portfolio"),
            st.Page(page_timing.render, title="진입 타이밍", icon="🎯",
                    url_path="timing"),
            st.Page(page_backtest.render, title="백테스트", icon="⏪",
                    url_path="backtest"),
            st.Page(page_agent.render, title="AI 에이전트", icon="🤖",
                    url_path="agent"),
        ],
        "시스템": [
            st.Page(page_quality.render, title="데이터 품질", icon="🔧",
                    url_path="quality"),
        ],
    }
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
