import base64
import json
import logging

import httpx

from config import settings
from schemas.search import Midpoint, PlaceItem

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
REPLY_MODEL = "deepseek-v4-flash"

BAILIAN_TTS_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)
TTS_MODEL = "qwen3-tts-flash"
TTS_VOICE = "Cherry"

REPLY_SYSTEM_PROMPT = """你是一个语音约碰面助手。根据用户提供的地址、中点位置和推荐店铺，生成一句适合朗读的中文播报语。

要求：
1. 只输出一句完整的话，口语自然，不要分点，不要 JSON。
2. 必须基于提供的店铺列表，店名和地址必须与列表一致，禁止编造。
3. 优先推荐第一家店，可简要说明这是两人中间附近的好选择。
4. 可提及两人的出发位置，让播报更亲切。
5. 长度控制在 80 字以内，方便收听。"""


class FinalizeError(Exception):
    def __init__(self, user_message: str, log_message: str) -> None:
        self.user_message = user_message
        self.log_message = log_message
        super().__init__(log_message)


def _get_deepseek_api_key() -> str:
    api_key = settings.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise FinalizeError(
            "播报服务未配置，请联系管理员。",
            "Finalize 失败：backend/.env 中未配置 DEEPSEEK_API_KEY。",
        )
    return api_key


def _get_bailian_api_key() -> str:
    api_key = settings.get("BAILIAN_API_KEY", "").strip()
    if not api_key:
        raise FinalizeError(
            "语音合成服务未配置，请联系管理员。",
            "Finalize 失败：backend/.env 中未配置 BAILIAN_API_KEY。",
        )
    return api_key


def _build_reply_context(
    midpoint: Midpoint,
    places: list[PlaceItem],
    address_a: str,
    address_b: str,
    category: str,
) -> str:
    return json.dumps(
        {
            "address_a": address_a,
            "address_b": address_b,
            "category": category,
            "midpoint": {"lng": midpoint.lng, "lat": midpoint.lat},
            "places": [{"name": place.name, "address": place.address} for place in places],
        },
        ensure_ascii=False,
    )


async def _generate_reply_text(
    client: httpx.AsyncClient,
    api_key: str,
    midpoint: Midpoint,
    places: list[PlaceItem],
    address_a: str,
    address_b: str,
    category: str,
) -> str:
    request_body = {
        "model": REPLY_MODEL,
        "messages": [
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请根据以下信息生成一句播报语：\n"
                    f"{_build_reply_context(midpoint, places, address_a, address_b, category)}"
                ),
            },
        ],
        "temperature": 0.3,
    }

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
        raise FinalizeError(
            "播报语生成失败，请稍后重试。",
            f"Finalize 失败：请求 DeepSeek 网络异常 - {exc}",
        ) from exc

    if response.status_code != 200:
        raise FinalizeError(
            "播报语生成失败，请稍后重试。",
            (
                f"Finalize 失败：DeepSeek 返回 HTTP {response.status_code}，"
                f"响应体：{response.text[:500]}"
            ),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FinalizeError(
            "播报语生成失败，请稍后重试。",
            f"Finalize 失败：DeepSeek 响应不是合法 JSON - {response.text[:500]}",
        ) from exc

    choices = payload.get("choices") or []
    if not choices:
        raise FinalizeError(
            "播报语生成失败，请稍后重试。",
            f"Finalize 失败：DeepSeek 未返回 choices，完整响应：{payload}",
        )

    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise FinalizeError(
            "播报语生成失败，请稍后重试。",
            f"Finalize 失败：DeepSeek 返回空播报语，完整响应：{payload}",
        )

    reply_text = content.strip().strip('"').strip("'")
    logger.info("【Finalize】DeepSeek 播报语生成成功，长度=%d", len(reply_text))
    return reply_text


async def _synthesize_speech(
    client: httpx.AsyncClient,
    api_key: str,
    text: str,
) -> tuple[bytes, str]:
    request_body = {
        "model": TTS_MODEL,
        "input": {
            "text": text,
            "voice": TTS_VOICE,
            "language_type": "Chinese",
        },
    }

    try:
        response = await client.post(
            BAILIAN_TTS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
    except httpx.RequestError as exc:
        raise FinalizeError(
            "语音合成失败，请稍后重试。",
            f"Finalize 失败：请求百炼 TTS 网络异常 - {exc}",
        ) from exc

    if response.status_code != 200:
        raise FinalizeError(
            "语音合成失败，请稍后重试。",
            (
                f"Finalize 失败：百炼 TTS 返回 HTTP {response.status_code}，"
                f"响应体：{response.text[:500]}"
            ),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FinalizeError(
            "语音合成失败，请稍后重试。",
            f"Finalize 失败：百炼 TTS 响应不是合法 JSON - {response.text[:500]}",
        ) from exc

    if payload.get("code"):
        raise FinalizeError(
            "语音合成失败，请稍后重试。",
            (
                f"Finalize 失败：百炼 TTS 返回错误 code={payload.get('code')} "
                f"message={payload.get('message')}"
            ),
        )

    audio_info = (payload.get("output") or {}).get("audio") or {}
    audio_url = audio_info.get("url")
    if audio_url:
        try:
            audio_response = await client.get(audio_url)
        except httpx.RequestError as exc:
            raise FinalizeError(
                "语音合成失败，请稍后重试。",
                f"Finalize 失败：下载 TTS 音频网络异常 - {exc}",
            ) from exc

        if audio_response.status_code != 200:
            raise FinalizeError(
                "语音合成失败，请稍后重试。",
                (
                    f"Finalize 失败：下载 TTS 音频 HTTP {audio_response.status_code}，"
                    f"url={audio_url}"
                ),
            )

        content_type = audio_response.headers.get("content-type", "audio/wav")
        logger.info(
            "【Finalize】百炼 TTS 合成成功，音频大小=%d content_type=%s",
            len(audio_response.content),
            content_type,
        )
        return audio_response.content, content_type

    audio_data = audio_info.get("data")
    if isinstance(audio_data, str) and audio_data:
        logger.info("【Finalize】百炼 TTS 合成成功，返回 base64 音频数据")
        return base64.b64decode(audio_data), "audio/wav"

    raise FinalizeError(
        "语音合成失败，请稍后重试。",
        f"Finalize 失败：百炼 TTS 未返回音频，完整响应：{payload}",
    )


async def finalize_meetup_reply(
    midpoint: Midpoint,
    places: list[PlaceItem],
    address_a: str = "",
    address_b: str = "",
    category: str = "",
) -> dict[str, str]:
    if not places:
        raise FinalizeError(
            "没有可推荐的地点，无法生成播报。",
            "Finalize 失败：places 列表为空。",
        )

    deepseek_key = _get_deepseek_api_key()
    bailian_key = _get_bailian_api_key()

    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        reply_text = await _generate_reply_text(
            client,
            deepseek_key,
            midpoint,
            places,
            address_a,
            address_b,
            category,
        )
        audio_bytes, content_type = await _synthesize_speech(client, bailian_key, reply_text)

    return {
        "reply_text": reply_text,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_content_type": content_type,
    }
