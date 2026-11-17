
from typing import Literal
from pydantic import BaseModel, Field


class GatewayRequest(BaseModel):
    provider: Literal["gemini", "groq"]
    prompt: str = Field(
        min_length=1,
        max_length=4000
    )


class GatewayResponse(BaseModel):
    provider: str
    model: str
    answer: str
    usage: dict
