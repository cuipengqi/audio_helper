from pydantic import BaseModel, Field

from schemas.search import Midpoint, PlaceItem


class FinalizeRequest(BaseModel):
    midpoint: Midpoint
    places: list[PlaceItem] = Field(..., min_length=1)
    address_a: str = ""
    address_b: str = ""
    category: str = ""


class FinalizeResponse(BaseModel):
    reply_text: str
    audio_base64: str
    audio_content_type: str
