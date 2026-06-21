# 🌊 Macro Quant Terminal v18

매크로 유동성 → 레짐 판단 → 자금흐름 → 섹터 로테이션 → 포트폴리오 자동화 Streamlit 앱.

## v18 핵심 변경 (vs v17.1)

| 영역 | v17.1 | v18 |
|---|---|---|
| 페이지 구조 | `st.tabs` 13개 전체 실행 | `st.navigation` 멀티페이지 — 선택 페이지만 실행 |
| MPT 최적화 | MC + clip→정규화 (상한 미작동 버그) | **SLSQP 제약 최적화** (max_asset/max_sector 강제), MC는 프론티어 시각화용 |
| 백테스트 | 3축 별도 로직 (실거래와 불일치) | 실거래와 **같은 `score_assets` 함수** (가격 5축) + 거래비용 차감 |
| 버핏지표 | 윌셔 판정구간 오적용 (~20% 왜곡) | 자체 히스토리 **z-score** 표시 |
| 유동성 | 일간 ffill MA20 비교 | **W-WED 리샘플 + z-score + 가속도**, WRESBAL 교차검증 |
| 단기국채 발행 | 없음 (원 기획 누락) | **재무부 FiscalData API** — Bill 순발행 vs RRP 해석 매트릭스, 경매 b2c, TGA 일간 |
| 지정학 | 수동 슬라이더 | **GDELT 뉴스볼륨 자동 점수** (수동 오버라이드 가능) |
| 자금흐름 | 없음 | **RRG 16자산** + 프록시 비율(HYG/LQD 등) + 스테이블코인 시총 |
| AI 테마 | 없음 | **밸류체인 5단계 바스켓** (설계→제조→클라우드→SW→전력) |
| 에이전트 | 자유 텍스트 LLM | **JSON 스키마 강제** + 트리거 엔진(LLM 없이 동작) |
| 레짐 | 즉시 전환 (휩쏘) | **히스테리시스 ±1.5** + Ledoit-Wolf 공분산 |

## 파일 구조

```
app.py                  # 진입점: 사이드바 + st.navigation
core/   config.py utils.py
data/   fred.py treasury.py market.py crypto.py news.py
engine/ liquidity.py regime.py scoring.py optimize.py risk.py backtest.py flows.py
agent/  triggers.py llm.py
ui/     common.py page_*.py (9개 페이지)
```

## 로컬 실행

```bash
pip install -r requirements.txt
# 선택: 환경변수 또는 .streamlit/secrets.toml
streamlit run app.py
```

`.streamlit/secrets.toml` 예시:

```toml
FRED_API_KEY = "..."        # 없으면 fredgraph CSV fallback (느림)
ANTHROPIC_API_KEY = "..."   # AI 에이전트 (선택)
GEMINI_API_KEY = "..."      # Anthropic 실패 시 fallback (선택)
```

## Streamlit Community Cloud 배포

1. GitHub 리포(예: `macro-quant-terminal`)에 이 폴더 전체 push
2. share.streamlit.io → New app → 리포/브랜치/`app.py` 선택
3. **App settings → Secrets**에 위 secrets.toml 내용 붙여넣기
4. 재배포 시 기존 앱은 자동 갱신 (requirements 변경 시 Reboot 권장)

## 주의

- 백테스트는 가격 5축만 검증(거래량/레짐/밸류 축 제외) — 화면에 경고 표시됨
- 개별주 백테스트는 생존편향 때문에 미제공
- GDELT/CoinGecko/FiscalData는 무료 API — 간헐 실패 시 '데이터 품질' 페이지에서 확인
- 본 앱의 모든 출력은 정보 제공 목적이며 투자 자문이 아닙니다


## v18.1 추가 (리스크 레이더 + 바벨 전략)

- **3-슬리브 바벨 전략** (포트폴리오 페이지): 선행(RRG 개선 사분면) + 모멘텀(주도) + 방어 앵커(레짐 연동 동적 12~60%). 모멘텀 추종의 후행성·하락장 리스크 해결. 백테스트 페이지에서 SPY/기존모멘텀과 3자 비교.
- **리스크 레이더** (신규 페이지):
  - 연준 대차대조표 상세 (총자산/국채/MBS/QT 속도/지준비율)
  - 금리 경로 (정책금리 + 국채커브 기반 시장 기대 — 공식 점도표는 API 없어 근사)
  - 스태그플레이션 게이지 (인플레↑ + 성장둔화 + 고용악화 동시조건, combo 증폭)
  - 폭락 리스크 게이지 3시간축 (1주 기술적/1달 신용유동성/1년 밸류매크로)
- **폭락→방어 연동**: 1달 폭락 리스크 ≥34점이면 바벨 방어비중 자동 상향
- FRED 시리즈 추가: TREAST, WSHOMCB, DFEDTARU, FEDFUNDS, PCEPILFE, INDPRO, ICSA, T10Y3M, DGS3MO, STLFSI4, GDPC1, BAMLC0A0CM

⚠️ **폭락 게이지는 확률 예측이 아닙니다.** 과거 폭락에 선행했던 조건이 현재 몇 개 켜져 있는지 보여주는 '경계 수준'입니다. 모두 켜져도 폭락하지 않을 수 있고 그 반대도 가능합니다.


## v18.2 추가 (진입 타이밍 / 조정 분할매수)

**진입 타이밍 페이지** (🎯) — 우상향 가정 하에 '언제 담을지':
- **합류(confluence) 분석**: 공포탐욕 + 지지/저항 근접 + 라운드넘버 + RSI 과매도 + 단기낙폭이 겹치는 가격대를 0~100 점수화. 여러 신호가 합류할 때만 강한 시그널.
- **지지/저항 자동 탐지**: 스윙 고저점 클러스터링 + 터치 횟수 가중 + 라운드넘버. 차트 자동 갱신.
- **분할매수 상태머신**: 공포 구간에서 트랜치 투입, 극도공포 시 1.5배. 탄약 상한·회차 제한으로 마틴게일 차단.
- **폭락장 차단기**: 금리·물가·스태그·신용·유동성·커브역전 경고를 누적. 3개 이상이면 조정매수 전면 차단 ('떨어지는 칼날' 방지). 원석님 우려('코로나급 긴 폭락장')의 핵심 안전장치.
- **장기 바닥 포착**: 차단 모드에서 주봉/월봉 장기지지선(200주 MA·월봉 스윙로우) + 패닉 소진 신호로 바닥 후보 식별.
- **백테스트**: 과거 공포구간 분할매수 vs 일괄매수 vs 매월적립 비교. '타이밍 노력이 단순 적립보다 나은가' 검증.
- 대상: 지수 ETF(SPY/QQQ/DIA) + 시총 상위 개별주(애플·엔비디아 등).

⚠️ **핵심 한계**: 이 전략은 '우상향 가정'에 의존합니다. 그 가정이 깨지는 긴 약세장은 차단기가 감지하지만 완벽하지 않습니다. "공포에 담는다"는 강세장 조정엔 강력하나 약세장 초입엔 위험 — 탄약 상한과 차단기를 반드시 신뢰하세요. 공격적 모드는 차단기가 작동할 때만 안전합니다.
