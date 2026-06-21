# core/config.py — 전역 상수
# v18: 시리즈/티커/가중치/시나리오를 한 곳에서 관리

# ──────────────────────────────────────────────
# FRED 시리즈: sid -> (발표주기, 나눗셈 변환(None=없음), 라벨)
# 주기: D=일간, W=주간, M=월간, Q=분기
FRED_SERIES = {
    "WALCL":        ("W", 1000, "Fed 총자산 ($bn)"),
    "WDTGAL":       ("W", 1000, "TGA 수요일 기준 ($bn)"),
    "WTREGEN":      ("W", 1000, "TGA 주간 평균 ($bn)"),
    "RRPONTSYD":    ("D", None, "역레포 RRP ($bn)"),
    "WRESBAL":      ("W", None, "은행 지급준비금 ($bn)"),   # v18 신규
    "M2SL":         ("M", None, "M2 ($bn)"),
    "DGS10":        ("D", None, "10년 금리 (%)"),
    "DGS2":         ("D", None, "2년 금리 (%)"),
    "DGS3MO":       ("D", None, "3개월 금리 (%)"),
    "T10Y2Y":       ("D", None, "10Y-2Y (%)"),
    "T10Y3M":       ("D", None, "10Y-3M (%)"),               # 침체 예측력 높은 커브
    "BAMLH0A0HYM2": ("D", None, "하이일드 스프레드 (%)"),
    "BAMLC0A0CM":   ("D", None, "투자등급 스프레드 (%)"),
    "NFCI":         ("W", None, "금융환경지수"),
    "STLFSI4":      ("W", None, "세인트루이스 금융스트레스"),
    "GDP":          ("Q", None, "명목 GDP ($bn)"),
    "GDPC1":        ("Q", None, "실질 GDP ($bn)"),
    "NCBEILQ027S":  ("Q", 1000, "비금융기업 주식시총 ($bn)"),
    "CPIAUCSL":     ("M", None, "CPI"),
    "PCEPILFE":     ("M", None, "Core PCE 물가"),
    "UNRATE":       ("M", None, "실업률 (%)"),
    "INDPRO":       ("M", None, "산업생산지수"),
    "ICSA":         ("W", None, "신규 실업수당 청구"),
    # ── 연준 대차대조표 상세 (v18.1 신규)
    "TREAST":       ("W", 1000, "Fed 보유 국채 ($bn)"),
    "WSHOMCB":      ("W", 1000, "Fed 보유 MBS ($bn)"),
    "DFEDTARU":     ("D", None, "연방기금 목표상단 (%)"),
    "FEDFUNDS":     ("M", None, "실효 연방기금금리 (%)"),
}

# ──────────────────────────────────────────────
# 섹터 스코어 가중치 — 합계 1.00 (v17.1 버그 7 수정: 자동 정규화도 scoring.py에서 수행)
DEFAULT_SCORE_W = {
    "rs_1m": 0.30, "rs_3m": 0.20, "volume": 0.12, "trend": 0.16,
    "low_vol": 0.10, "drawdown": 0.05, "macro_fit": 0.05, "valuation": 0.02,
}

SECTOR_ETFS = {
    "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Financials": "XLF",
    "Health Care": "XLV", "Industrials": "XLI", "Materials": "XLB",
    "Real Estate": "XLRE", "Technology": "XLK", "Utilities": "XLU",
}

SECTOR_STOCKS = {
    "Communication Services": ["GOOGL","META","NFLX","DIS","TMUS","CMCSA"],
    "Consumer Discretionary": ["AMZN","TSLA","HD","MCD","NKE","BKNG"],
    "Consumer Staples": ["PG","COST","WMT","KO","PEP","PM"],
    "Energy": ["XOM","CVX","COP","SLB","EOG","OXY"],
    "Financials": ["JPM","BAC","WFC","GS","MS","BLK"],
    "Health Care": ["LLY","UNH","JNJ","ABBV","MRK","TMO"],
    "Industrials": ["GE","CAT","RTX","HON","UNP","DE"],
    "Materials": ["LIN","SHW","FCX","NEM","APD","ECL"],
    "Real Estate": ["PLD","AMT","EQIX","WELL","SPG","DLR"],
    "Technology": ["NVDA","MSFT","AAPL","AVGO","AMD","ORCL"],
    "Utilities": ["NEE","SO","DUK","AEP","SRE","EXC"],
}

# ──────────────────────────────────────────────
# 진입 타이밍 분석 대상 (v18.2)
TIMING_INDEX = {
    "S&P500 (SPY)": "SPY",
    "나스닥100 (QQQ)": "QQQ",
    "다우 (DIA)": "DIA",
}
TIMING_MEGACAP = {
    "Apple": "AAPL", "Microsoft": "MSFT", "Nvidia": "NVDA",
    "Amazon": "AMZN", "Alphabet": "GOOGL", "Meta": "META",
    "Broadcom": "AVGO", "Tesla": "TSLA",
}
TIMING_DEFAULTS = {
    "aggression": "공격적",
    "fg_enter": 25, "fg_extreme": 15,
    "max_rounds": 5, "ammo_per_round": 0.18, "support_tol": 0.03,
}

# v18 신규 — AI 밸류체인 바스켓 (§7)
AI_BASKET = {
    "반도체(설계)": ["NVDA","AMD","AVGO","ARM"],
    "반도체(제조/장비)": ["TSM","ASML","AMAT","LRCX","MU"],
    "클라우드/하이퍼스케일러": ["MSFT","GOOGL","AMZN","META","ORCL"],
    "AI 소프트웨어": ["PLTR","NOW","CRM","SNOW"],
    "전력/인프라": ["VRT","ETN","NEE","CEG"],
}

# v18 신규 — 크로스에셋 자금흐름 유니버스 (§5, RRG)
FLOW_UNIVERSE = {
    "미국 대형성장": "QQQ", "미국 가치": "IWD", "미국 소형": "IWM",
    "선진국(exUS)": "EFA", "신흥국": "EEM", "한국": "EWY",
    "장기채": "TLT", "단기채": "SHY", "하이일드": "HYG",
    "금": "GLD", "은": "SLV", "원유": "USO", "구리": "CPER",
    "비트코인": "BTC-USD", "이더리움": "ETH-USD", "달러": "UUP",
}
FLOW_BENCH = "ACWI"   # 글로벌 벤치마크

# 자금흐름 프록시 비율 (분자, 분모, 해석)
FLOW_RATIOS = {
    "HYG/LQD (크레딧 위험선호)": ("HYG", "LQD"),
    "구리/금 (성장 vs 안전)": ("CPER", "GLD"),
    "RSP/SPY (시장 폭)": ("RSP", "SPY"),
    "IWM/SPY (소형주 선호)": ("IWM", "SPY"),
}
FLOW_RATIO_TICKERS = ["HYG","LQD","CPER","GLD","RSP","SPY","IWM"]

GLOBAL_INDICES = {
    "S&P500": "^GSPC", "나스닥": "^IXIC", "DOW": "^DJI",
    "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "닛케이": "^N225", "항셍": "^HSI",
    "DAX": "^GDAXI", "VIX": "^VIX", "달러인덱스": "DX-Y.NYB",
    "원달러": "KRW=X", "TLT(장기채)": "TLT", "GLD(금)": "GLD",
}

COMMODITIES = {
    "WTI 원유": "CL=F", "브렌트": "BZ=F", "금": "GC=F",
    "은": "SI=F", "구리": "HG=F", "천연가스": "NG=F",
}

CRYPTO_TICKERS = {"Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "BNB": "BNB-USD"}
STABLECOINS = ["tether", "usd-coin", "dai"]   # CoinGecko id

KR_ETFS = {"KOSPI200": "069500.KS", "KOSDAQ150": "229200.KS",
           "KR반도체": "091160.KS", "KR인버스": "114800.KS"}

# ──────────────────────────────────────────────
# 자산 분류 (스트레스 테스트용): ticker -> class
GROWTH_SECTORS = {"XLK","XLC","XLY"}
DEFENSE_SECTORS = {"XLP","XLU","XLV"}
RATE_SENSITIVE = {"XLRE","XLU","XLK"}
FIN_ENERGY = {"XLF","XLE"}

def asset_class(t: str) -> str:
    if t.endswith("-USD"): return "crypto"
    if t in ("TLT","IEF","SHY"): return "bond"
    if t in ("GLD","GC=F"): return "gold"
    if t in GROWTH_SECTORS: return "growth"
    if t in DEFENSE_SECTORS: return "defense"
    if t in FIN_ENERGY: return "fin_energy"
    if t in RATE_SENSITIVE: return "rate_sens"
    return "equity"

# 시나리오: class -> 충격(%) (v17.1 §11 유지)
STRESS_SCENARIOS = {
    "주식 급락": {"growth": -16, "equity": -10, "defense": -6, "fin_energy": -10,
                 "rate_sens": -12, "bond": +6, "gold": +3, "crypto": -25},
    "금리 재상승": {"rate_sens": -10, "growth": -8, "equity": -4, "defense": -3,
                  "fin_energy": +2, "bond": -10, "gold": -4, "crypto": -8},
    "지정학 충격": {"fin_energy": +6, "equity": -5, "growth": -6, "defense": -1,
                  "rate_sens": -4, "bond": +3, "gold": +8, "crypto": -12},
    "소프트랜딩": {"growth": +8, "equity": +6, "fin_energy": +5, "defense": +2,
                 "rate_sens": +4, "bond": +1, "gold": 0, "crypto": +10},
}

# PER 패널티 (v17.1 유지)
def pe_penalty(pe):
    if pe is None or pe != pe: return 0.0
    if pe < 18: return 0.0
    if pe < 25: return -0.1
    if pe < 35: return -0.25
    return -0.5

# 매크로 적합도 규칙 (v17.1 §8 유지) — engine/scoring.py에서 사용
AGGRESSIVE = {"Technology","Communication Services","Consumer Discretionary",
              "Industrials","Materials","Financials"}
DEFENSIVE = {"Utilities","Consumer Staples","Health Care"}

# ──────────────────────────────────────────────
# 지정학/뉴스 키워드 (§4)
NEWS_CATEGORIES = {
    "전쟁/분쟁": ["war", "invasion", "missile strike", "military conflict"],
    "무역/제재": ["sanctions", "tariff", "export controls", "trade war"],
    "통화정책": ["rate hike", "rate cut", "FOMC", "quantitative tightening"],
    "정치 리스크": ["government shutdown", "debt ceiling", "election uncertainty"],
}

# LLM (§8)
LLM_LIMIT = 5
ANTHROPIC_MODEL = "claude-sonnet-4-5"
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
