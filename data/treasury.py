# data/treasury.py — 미 재무부 FiscalData API (무료, 키 불필요)  §3
import requests
import pandas as pd
import streamlit as st
from datetime import date, timedelta

from core.utils import record

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


def _get_pages(endpoint: str, params: dict, max_pages: int = 6) -> pd.DataFrame:
    rows, page = [], 1
    size = int(params.get("page[size]", 5000))
    while page <= max_pages:
        p = dict(params, **{"page[number]": page, "page[size]": size})
        r = requests.get(f"{BASE}{endpoint}", params=p, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
        rows.extend(data)
        if len(data) < size:
            break
        page += 1
    return pd.DataFrame(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_bill_flows(days: int = 420) -> pd.DataFrame | None:
    """일간 국채 발행/상환(DTS Table) → 주간(W-WED) Bill 순발행 ($bn)"""
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        df = _get_pages(
            "/v1/accounting/dts/public_debt_transactions",
            {"filter": f"record_date:gte:{start}",
             "fields": ("record_date,transaction_type,security_market,"
                        "security_type,transaction_today_amt"),
             "page[size]": 9000},
        )
        if df.empty:
            raise RuntimeError("빈 응답")
        df["record_date"] = pd.to_datetime(df["record_date"])
        df["amt"] = pd.to_numeric(df["transaction_today_amt"], errors="coerce") / 1000.0  # $mn→$bn
        m = (df["security_market"].str.contains("Marketable", case=False, na=False)
             & df["security_type"].str.contains("Bill", case=False, na=False))
        df = df[m]
        piv = (df.pivot_table(index="record_date", columns="transaction_type",
                              values="amt", aggfunc="sum").fillna(0.0))
        iss = piv.filter(like="Issu").sum(axis=1)
        red = piv.filter(like="Redem").sum(axis=1)
        out = pd.DataFrame({"발행": iss, "상환": red})
        out["순발행"] = out["발행"] - out["상환"]
        wk = out.resample("W-WED").sum()
        record("Treasury:bill_flows", True, f"{len(wk)}주, 최신 {wk.index[-1].date()}")
        return wk
    except Exception as e:                       # noqa: BLE001
        record("Treasury:bill_flows", False, str(e)[:120])
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_auctions(days: int = 200) -> pd.DataFrame | None:
    """경매 결과: Bill 응찰배율(bid-to-cover) 추이 — 수요 약화 감지"""
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        df = _get_pages(
            "/v1/accounting/od/auctions_query",
            {"filter": f"auction_date:gte:{start}",
             "fields": ("auction_date,security_type,security_term,"
                        "offering_amt,bid_to_cover_ratio"),
             "sort": "-auction_date", "page[size]": 2000},
        )
        if df.empty:
            raise RuntimeError("빈 응답")
        df["auction_date"] = pd.to_datetime(df["auction_date"])
        df["offering_amt"] = pd.to_numeric(df["offering_amt"], errors="coerce")
        # 단위 정규화: 달러로 오면 $bn으로
        med = df["offering_amt"].median()
        if med and med > 1e7:
            df["offering_amt"] = df["offering_amt"] / 1e9
        df["bid_to_cover_ratio"] = pd.to_numeric(df["bid_to_cover_ratio"], errors="coerce")
        df = df[df["security_type"].str.contains("Bill", case=False, na=False)]
        record("Treasury:auctions", True, f"{len(df)}건")
        return df.sort_values("auction_date")
    except Exception as e:                       # noqa: BLE001
        record("Treasury:auctions", False, str(e)[:120])
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_tga_daily(days: int = 420) -> pd.Series | None:
    """TGA 일간 잔고 (DTS) — FRED 주간보다 빠름. 실패 시 None → FRED 사용"""
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        df = _get_pages(
            "/v1/accounting/dts/operating_cash_balance",
            {"filter": f"record_date:gte:{start}", "page[size]": 3000},
        )
        if df.empty:
            raise RuntimeError("빈 응답")
        df["record_date"] = pd.to_datetime(df["record_date"])
        acct = df.get("account_type", pd.Series(dtype=str)).astype(str)
        mask = acct.str.contains("Treasury General Account", case=False, na=False)
        if mask.any():
            sub = df[mask]
            close_mask = sub["account_type"].str.contains("Clos", case=False, na=False)
            if close_mask.any():
                sub = sub[close_mask]
        else:  # 구포맷
            sub = df[acct.str.contains("Federal Reserve Account", case=False, na=False)]
        # 금액 컬럼 탐색 (포맷 변천 대응)
        col = next((c for c in ["close_today_bal", "open_today_bal"] if c in sub.columns), None)
        if col is None or sub.empty:
            raise RuntimeError("TGA 컬럼/계정 식별 실패")
        s = (pd.to_numeric(sub.set_index("record_date")[col], errors="coerce")
             .dropna().sort_index() / 1000.0)   # $mn → $bn
        s = s[~s.index.duplicated(keep="last")]
        record("Treasury:TGA_daily", True, f"최신 {s.index[-1].date()}")
        return s
    except Exception as e:                       # noqa: BLE001
        record("Treasury:TGA_daily", False, str(e)[:120])
        return None


def bill_liquidity_matrix(net_bill_4w: float | None, rrp_now: float | None,
                          rrp_chg_4w: float | None) -> tuple[str, str]:
    """§3-2 해석 매트릭스 → (판정문, 등급이모지)"""
    if net_bill_4w is None or rrp_now is None:
        return "데이터 부족 — 판정 불가", "⚪"
    if net_bill_4w > 50:
        if rrp_chg_4w is not None and rrp_chg_4w < -20:
            return ("Bill 순발행 증가 + RRP 감소 → MMF가 RRP에서 Bill로 이동. "
                    "시장 유동성 중립 (흡수 상쇄)"), "🟡"
        if rrp_now < 100:
            return ("Bill 순발행 증가 + RRP 바닥 → 은행 지급준비금에서 직접 흡수. "
                    "유동성 마이너스 경고"), "🔴"
        return "Bill 순발행 증가 — RRP 완충 여력 관찰 필요", "🟡"
    if net_bill_4w < -30:
        return "Bill 순상환 — 단기 유동성 방출 (긍정적)", "🟢"
    return "Bill 발행 중립", "⚪"
