import json
import logging
import re

import httpx

from config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
EXTRACT_MODEL = "deepseek-v4-flash"
DEFAULT_CATEGORY = "咖啡店"

SYSTEM_PROMPT = """你是一个地址与意图提取助手。用户会描述两个人在哪里、想在哪里碰面做什么。
你的任务是从用户输入中提取信息，且只输出一个 JSON 对象，不要输出任何其他文字。

输出格式（严格遵守）：
{
  "address_a": "<说话者自己的位置，保留用户原话中的地名表述>",
  "address_b": "<朋友的位置，保留用户原话中的地名表述>",
  "category": "<碰面想做什么，如咖啡店、餐厅、公园等>"
}

规则：
1. 只提取用户明确说出的信息，不要猜测或补充未提及的地址。
2. address_a 是「我」所在位置，address_b 是「朋友」所在位置。
3. 若用户未说明碰面想做什么，category 默认为「咖啡店」。
4. 只输出 JSON，不要用 markdown 代码块包裹。"""


class ExtractError(Exception):
    def __init__(self, user_message: str, log_message: str) -> None:
        self.user_message = user_message
        self.log_message = log_message
        super().__init__(log_message)


def _get_api_key() -> str:
    api_key = settings.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ExtractError(
            "信息提取服务未配置，请联系管理员。",
            "Extract 失败：backend/.env 中未配置 DEEPSEEK_API_KEY。",
        )
    return api_key


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_extract_payload(raw_content: str) -> dict[str, str]:
    try:
        payload = json.loads(_strip_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise ExtractError(
            "未能理解您的描述，请说清楚两个位置后再试。",
            f"Extract 失败：JSON 解析错误 - {exc}，原始内容：{raw_content[:500]}",
        ) from exc

    if not isinstance(payload, dict):
        raise ExtractError(
            "未能理解您的描述，请说清楚两个位置后再试。",
            f"Extract 失败：解析结果不是 JSON 对象，原始内容：{raw_content[:500]}",
        )

    address_a = str(payload.get("address_a", "")).strip()
    address_b = str(payload.get("address_b", "")).strip()
    category = str(payload.get("category", "")).strip() or DEFAULT_CATEGORY

    missing_fields = [
        name
        for name, value in (("address_a", address_a), ("address_b", address_b))
        if not value
    ]
    if missing_fields:
        raise ExtractError(
            "未能从话里听清两个地址，请分别说出您和朋友的位置。",
            f"Extract 失败：字段缺失 {missing_fields}，解析结果：{payload}",
        )

    return {
        "address_a": address_a,
        "address_b": address_b,
        "category": category,
    }


async def extract_meetup_info(text: str) -> dict[str, str]:
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ExtractError(
            "识别文字为空，请重新录制。",
            "Extract 失败：输入文字为空。",
        )

    api_key = _get_api_key()
    request_body = {
        "model": EXTRACT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": cleaned_text},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
        except httpx.RequestError as exc:
            raise ExtractError(
                "信息提取服务暂时不可用，请稍后重试。",
                f"Extract 失败：请求 DeepSeek 网络异常 - {exc}",
            ) from exc

    if response.status_code != 200:
        raise ExtractError(
            "信息提取失败，请重新说一遍两个地址。",
            (
                f"Extract 失败：DeepSeek 返回 HTTP {response.status_code}，"
                f"响应体：{response.text[:500]}"
            ),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ExtractError(
            "信息提取失败，请重新说一遍两个地址。",
            f"Extract 失败：DeepSeek 响应不是合法 JSON - {response.text[:500]}",
        ) from exc

    choices = payload.get("choices") or []
    if not choices:
        raise ExtractError(
            "信息提取失败，请重新说一遍两个地址。",
            f"Extract 失败：DeepSeek 未返回 choices，完整响应：{payload}",
        )

    message = choices[0].get("message") or {}
    raw_content = message.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise ExtractError(
            "信息提取失败，请重新说一遍两个地址。",
            f"Extract 失败：DeepSeek 返回内容为空，完整响应：{payload}",
        )

    result = _parse_extract_payload(raw_content)
    logger.info(
        "【Extract】审核通过：address_a=%s address_b=%s category=%s",
        result["address_a"],
        result["address_b"],
        result["category"],
    )
    return result
