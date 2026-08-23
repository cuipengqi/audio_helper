import base64
import logging
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

BAILIAN_ASR_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)
ASR_MODEL = "qwen3-asr-flash"

MIME_BY_SUFFIX = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


class AsrError(Exception):
    def __init__(self, user_message: str, log_message: str) -> None:
        self.user_message = user_message
        self.log_message = log_message
        super().__init__(log_message)


def _get_api_key() -> str:
    api_key = settings.get("BAILIAN_API_KEY", "").strip()
    if not api_key:
        raise AsrError(
            "语音识别服务未配置，请联系管理员。",
            "ASR 失败：backend/.env 中未配置 BAILIAN_API_KEY。",
        )
    return api_key


def _guess_mime_type(filename: str | None, content_type: str | None) -> str:
    if content_type and content_type.startswith("audio/"):
        return content_type.split(";")[0]
    suffix = Path(filename or "").suffix.lower()
    return MIME_BY_SUFFIX.get(suffix, "audio/webm")


def _build_data_uri(audio_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_text(payload: dict) -> str:
    output = payload.get("output") or {}
    choices = output.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            texts = [
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("text")
            ]
            if texts:
                return "".join(texts)
        if isinstance(content, str):
            return content.strip()

    openai_choices = payload.get("choices") or []
    if openai_choices:
        message = openai_choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    return ""


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str | None,
    content_type: str | None,
) -> str:
    api_key = _get_api_key()
    mime_type = _guess_mime_type(filename, content_type)
    data_uri = _build_data_uri(audio_bytes, mime_type)

    request_body = {
        "model": ASR_MODEL,
        "input": {
            "messages": [
                {"role": "system", "content": [{"text": ""}]},
                {"role": "user", "content": [{"audio": data_uri}]},
            ]
        },
        "parameters": {
            "asr_options": {
                "enable_itn": False,
                "language": "zh",
            }
        },
    }

    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        try:
            response = await client.post(
                BAILIAN_ASR_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
        except httpx.RequestError as exc:
            raise AsrError(
                "语音识别服务暂时不可用，请稍后重试。",
                f"ASR 失败：请求百炼接口网络异常 - {exc}",
            ) from exc

    if response.status_code != 200:
        raise AsrError(
            "语音识别失败，请重新录制后再试。",
            (
                f"ASR 失败：百炼接口返回 HTTP {response.status_code}，"
                f"响应体：{response.text[:500]}"
            ),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise AsrError(
            "语音识别失败，请重新录制后再试。",
            f"ASR 失败：百炼响应不是合法 JSON - {response.text[:500]}",
        ) from exc

    if payload.get("code"):
        raise AsrError(
            "语音识别失败，请重新录制后再试。",
            (
                f"ASR 失败：百炼返回错误 code={payload.get('code')} "
                f"message={payload.get('message')}"
            ),
        )

    text = _extract_text(payload)
    if not text:
        logger.error("ASR 失败：识别结果为空，完整响应：%s", payload)
        raise AsrError(
            "没有识别到有效语音内容，请靠近麦克风重新录制。",
            "ASR 失败：识别结果为空。",
        )

    logger.info("【ASR】审核通过：识别文字长度=%d", len(text))
    return text
