from pydantic import BaseModel, Field
from typing import List, Optional, Any


class GeminiResponse(BaseModel):
    text: str = ""
    content: str = ""
    answer: str = ""
    candidates: List[Any] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
