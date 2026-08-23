import logging
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from config import settings
from schemas.extract import ExtractRequest, ExtractResponse
from schemas.finalize import FinalizeRequest, FinalizeResponse
from schemas.search import SearchRequest, SearchResponse
from services.amap import SearchError, search_meetup_places
from services.asr import AsrError, transcribe_audio
from services.extract import ExtractError, extract_meetup_info
from services.finalize import FinalizeError, finalize_meetup_reply

logging.basicConfig(level=logging.INFO)

STORAGE_DIR = Path(__file__).resolve().parent / "storage"

app = FastAPI(title="语音约碰面后端")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    # 启动时加载 backend/.env，后续模块通过 config.settings 读取
    _ = settings
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "语音约碰面后端已启动"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)) -> dict[str, str | bool]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".webm", ".ogg", ".wav", ".mp3", ".m4a"}:
        suffix = ".webm"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"audio_{timestamp}{suffix}"
    save_path = STORAGE_DIR / filename

    content = await file.read()
    if not content:
        logging.error("【上传】审核失败：上传的音频文件为空")
        raise HTTPException(status_code=400, detail="音频文件为空，请重新录制。")

    async with aiofiles.open(save_path, "wb") as saved_file:
        await saved_file.write(content)

    logging.info(
        "【上传】审核通过：文件已保存 filename=%s size=%d",
        filename,
        len(content),
    )
    return {"success": True, "filename": filename}


@app.post("/asr")
async def asr_audio(file: UploadFile = File(...)) -> dict[str, str]:
    content = await file.read()
    if not content:
        logging.error("【ASR】审核失败：上传的音频文件为空")
        raise HTTPException(status_code=400, detail="音频文件为空，请重新录制。")

    try:
        text = await transcribe_audio(content, file.filename, file.content_type)
    except AsrError as exc:
        logging.error(exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    logging.info("【ASR】审核通过：识别文字长度=%d", len(text))
    return {"text": text}


@app.post("/extract", response_model=ExtractResponse)
async def extract_info(body: ExtractRequest) -> ExtractResponse:
    try:
        result = await extract_meetup_info(body.text)
    except ExtractError as exc:
        logging.error(exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    logging.info(
        "【Extract】审核通过：address_a=%s address_b=%s category=%s",
        result["address_a"],
        result["address_b"],
        result["category"],
    )
    return ExtractResponse(**result)


@app.post("/search", response_model=SearchResponse)
async def search_places(body: SearchRequest) -> SearchResponse:
    try:
        result = await search_meetup_places(
            body.address_a,
            body.address_b,
            body.category,
        )
    except SearchError as exc:
        logging.error(exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    midpoint = result["midpoint"]
    logging.info(
        "【Search】审核通过：中点=(%f,%f) 地点数=%d",
        midpoint["lng"],
        midpoint["lat"],
        len(result["places"]),
    )
    return SearchResponse(**result)


@app.post("/finalize", response_model=FinalizeResponse)
async def finalize_reply(body: FinalizeRequest) -> FinalizeResponse:
    try:
        result = await finalize_meetup_reply(
            body.midpoint,
            body.places,
            body.address_a,
            body.address_b,
            body.category,
        )
    except FinalizeError as exc:
        logging.error(exc.log_message)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    logging.info(
        "【Finalize】审核通过：播报语长度=%d 音频 base64 长度=%d",
        len(result["reply_text"]),
        len(result["audio_base64"]),
    )
    return FinalizeResponse(**result)
