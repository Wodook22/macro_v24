# agent/llm.py — 에이전트화 (§8): 데이터 → 구조화 판단 → 리밸런싱 제안
import json
import re

from core.config import ANTHROPIC_MODEL, GEMINI_MODELS

SCHEMA_HINT = """{
  "market_view": {"regime": "Risk-On|Mixed|Risk-Off", "confidence": 0.0~1.0,
                  "key_drivers": ["근거 지표 2~4개"]},
  "liquidity_flow": {"from": ["이탈 자산군"], "to": ["유입 자산군"],
                     "evidence": ["근거"]},
  "portfolio_actions": [
    {"asset": "티커", "current_w": 0.0, "suggested_w": 0.0,
     "rationale": "근거", "evidence_ids": ["지표명"],
     "urgency": "now|this_week|watch"}
  ],
  "risk_flags": ["리스크 1~3개"],
  "invalidation": "이 시나리오가 틀렸다고 판단할 조건"
}"""

SYSTEM_AGENT = (
    "당신은 퀀트 포트폴리오 분석가입니다. 제공된 데이터만 근거로 판단하세요. "
    "매수/매도 '지시'가 아닌 '시나리오별 제안'이며, 모든 제안에 근거 지표를 명시합니다. "
    "응답은 아래 JSON 스키마로만 하세요. 마크다운 코드펜스, 설명문 등 JSON 외 텍스트 금지.\n"
    f"스키마:\n{SCHEMA_HINT}"
)


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def _call_anthropic(prompt: str, key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=2000,
        system=SYSTEM_AGENT,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _call_gemini(prompt: str, key: str) -> str:
    # 신버전 google-genai SDK 우선 시도, 구버전(google-generativeai) fallback
    last = None
    for m in GEMINI_MODELS:
        try:
            try:
                from google import genai as new_genai
                client = new_genai.Client(api_key=key)
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config={"system_instruction": SYSTEM_AGENT,
                            "max_output_tokens": 2000})
                return resp.text
            except ImportError:
                import google.generativeai as genai  # type: ignore[import]
                genai.configure(api_key=key)
                model = genai.GenerativeModel(m, system_instruction=SYSTEM_AGENT)
                return model.generate_content(prompt).text
        except Exception as e:                   # noqa: BLE001
            last = e
    raise RuntimeError(f"Gemini 전 모델 실패: {last}")


def call_agent(context_md: str, anthropic_key: str = "",
               gemini_key: str = "") -> tuple[dict | None, str, str]:
    """반환: (파싱된 JSON 또는 None, 원문, 사용 제공자)"""
    prompt = (
        "아래는 앱이 계산한 현재 시장/포트폴리오 상태입니다. "
        "이를 근거로 스키마에 맞는 JSON으로만 응답하세요.\n\n" + context_md)
    errors = []
    if anthropic_key:
        try:
            raw = _call_anthropic(prompt, anthropic_key)
            return _extract_json(raw), raw, "Anthropic"
        except Exception as e:                   # noqa: BLE001
            errors.append(f"Anthropic: {e}")
    if gemini_key:
        try:
            raw = _call_gemini(prompt, gemini_key)
            return _extract_json(raw), raw, "Gemini"
        except Exception as e:                   # noqa: BLE001
            errors.append(f"Gemini: {e}")
    return None, " / ".join(errors) if errors else "API 키 없음", "없음"
