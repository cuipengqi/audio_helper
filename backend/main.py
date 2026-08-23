from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from config import settings

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
    async with aiofiles.open(save_path, "wb") as saved_file:
        await saved_file.write(content)

    return {"success": True, "filename": filename}
