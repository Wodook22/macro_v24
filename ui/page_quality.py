# ui/page_quality.py — 데이터 품질/신선도 진단 (§부록B)
import pandas as pd
import streamlit as st

from core.config import FRED_SERIES
from core.utils import STATUS
from data.fred import load_fred_series

# 발표주기별 허용 지연일 (이보다 오래되면 '지연' 판정)
# 시리즈별 실제 발표 지연 허용 기준
# M2SL: 약 6~8주 지연 발표 / GDP·분기: 최대 5개월 지연 가능
STALE_DAYS = {"D": 5, "W": 12, "M": 80, "Q": 160}

# 시리즈별 개별 오버라이드 (특히 느린 시리즈)
STALE_OVERRIDE = {
    "M2SL": 90,           # 약 6~8주 발표 지연
    "NCBEILQ027S": 180,   # 분기 + 집계 지연
    "GDP": 180,           # 분기 + 수정치 지연
    "GDPC1": 180,         # 실질 GDP
    "PCEPILFE": 75,       # Core PCE 약 한 달 지연
    "INDPRO": 75,         # 산업생산
    "FEDFUNDS": 60,       # 월간 실효금리
}


def render():
    st.title("🔧 데이터 품질")
    st.caption("이번 세션에서 호출된 데이터 소스의 성공/실패와 "
               "FRED 시리즈 최신성을 진단합니다.")

    # ── FRED 시리즈 신선도
    st.subheader("FRED 시리즈 신선도")
    rows = []
    with st.spinner("FRED 시리즈 확인 중..."):
        for sid, (freq, _, label) in FRED_SERIES.items():
            s = load_fred_series(sid)
            if s is None or s.dropna().empty:
                rows.append({"시리즈": sid, "설명": label, "주기": freq,
                             "최신일": "—", "경과일": None, "판정": "❌ 로드 실패"})
                continue
            last = s.dropna().index[-1]
            age = (pd.Timestamp.today().normalize() - last).days
            limit = STALE_OVERRIDE.get(sid, STALE_DAYS.get(freq, 30))
            verdict = "✅ 정상" if age <= limit else f"⚠️ 지연 (허용 {limit}일)"
            rows.append({"시리즈": sid, "설명": label, "주기": freq,
                         "최신일": last.strftime("%Y-%m-%d"),
                         "경과일": age, "판정": verdict})
    df = pd.DataFrame(rows)
    n_bad = int(df["판정"].str.startswith(("⚠️", "❌")).sum())
    if n_bad:
        st.warning(f"{n_bad}개 시리즈에 문제가 있습니다 — "
                   "레짐/유동성 판단 신뢰도가 낮아질 수 있습니다.")
    else:
        st.success("모든 FRED 시리즈 정상")
    st.dataframe(df, width="stretch", hide_index=True)

    # ── 세션 호출 소스 상태
    st.subheader("데이터 소스 호출 로그 (이번 세션)")
    if not STATUS:
        st.caption("아직 기록 없음 — 다른 페이지를 먼저 방문하면 채워집니다.")
        return
    log = pd.DataFrame([
        {"소스": k, "상태": "✅" if v["ok"] else "❌",
         "메시지": v["msg"], "시각": v["at"]}
        for k, v in sorted(STATUS.items())])
    fails = log[log["상태"] == "❌"]
    if not fails.empty:
        st.error(f"{len(fails)}개 소스 실패 — 해당 데이터를 쓰는 지표는 "
                 "fallback 값이거나 표시되지 않습니다.")
    st.dataframe(log, width="stretch", hide_index=True)

    st.caption("캐시 TTL: 시장가격 15분 · FRED/GDELT 1시간 · ETF P/E 6시간. "
               "강제 갱신은 우측 상단 메뉴의 'Clear cache' 또는 아래 버튼.")
    if st.button("🔄 캐시 전체 비우기"):
        st.cache_data.clear()
        st.rerun()
