from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ExtractResponse(BaseModel):
    address_a: str
    address_b: str
    category: str
