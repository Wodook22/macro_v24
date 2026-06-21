# data/crypto.py — CoinGecko (도미넌스 + 스테이블코인 시총)  §5-2
# 429 대응: TTL 증가 + 재시도 지연 + 코인별 순차 지연
import time
import pandas as pd
import streamlit as st

from core.config import STABLECOINS
from core.utils import record


def _cg():
    from pycoingecko import CoinGeckoAPI
    return CoinGeckoAPI()


@st.cache_data(ttl=1800, show_spinner=False)   # 30분 → 429 감소
def fetch_global() -> dict | None:
    for attempt in range(3):
        try:
            g = _cg().get_global()
            g = g.get("data", g)
            out = {
                "btc_dominance": g["market_cap_percentage"].get("btc"),
                "eth_dominance": g["market_cap_percentage"].get("eth"),
                "total_mcap_bn": g["total_market_cap"].get("usd", 0) / 1e9,
            }
            record("CoinGecko:global", True)
            return out
        except Exception as e:                   # noqa: BLE001
            if "429" in str(e) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            record("CoinGecko:global", False, str(e)[:80])
            return None
    return None


@st.cache_data(ttl=21600, show_spinner=False)  # 6시간 (1시간→6시간, 429 근본 해결)
def fetch_stablecoin_mcap(days: int = 90) -> pd.Series | None:
    """USDT+USDC+DAI 시총 합계 일간 시계열 ($bn).
    증가 = 크립토 시장으로 신규 달러 유입 (도미넌스보다 직접적 유동성 프록시)
    TTL 6시간: 일간 데이터라 자주 갱신 불필요 + CoinGecko 무료 레이트리밋 대응"""
    cg = _cg()
    total = None
    try:
        for i, cid in enumerate(STABLECOINS):
            if i > 0:
                time.sleep(1.5)                  # 코인 간 요청 간격
            for attempt in range(3):
                try:
                    d = cg.get_coin_market_chart_by_id(cid, "usd", days=days)
                    break
                except Exception as e:           # noqa: BLE001
                    if "429" in str(e) and attempt < 2:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise
            mc = pd.DataFrame(d["market_caps"], columns=["ts", cid])
            mc["ts"] = pd.to_datetime(mc["ts"], unit="ms").dt.normalize()
            s = mc.groupby("ts")[cid].last() / 1e9
            total = s if total is None else total.add(s, fill_value=0)
        total = total.dropna()
        record("CoinGecko:stablecoin", True, f"{len(total)}일")
        return total
    except Exception as e:                       # noqa: BLE001
        record("CoinGecko:stablecoin", False, str(e)[:80])
        return None
