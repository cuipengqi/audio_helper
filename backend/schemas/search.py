from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    address_a: str = Field(..., min_length=1)
    address_b: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)


class Midpoint(BaseModel):
    lng: float
    lat: float


class PlaceItem(BaseModel):
    name: str
    address: str


class SearchResponse(BaseModel):
    midpoint: Midpoint
    places: list[PlaceItem]
