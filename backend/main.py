from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from config import settings

app = FastAPI(title="语音约碰面后端")


@app.on_event("startup")
async def startup() -> None:
    # 启动时加载 backend/.env，后续模块通过 config.settings 读取
    _ = settings


@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "语音约碰面后端已启动"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
