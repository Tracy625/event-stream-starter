from typing import List

from pydantic import BaseModel, Field, validator


class RefineModel(BaseModel):
    type: str = Field(..., min_length=1, max_length=40)
    summary: str = Field(..., min_length=4, max_length=80)
    impacted_assets: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(...)
    confidence: float

    @validator("reasons")
    def _reasons_len(cls, v):
        if not isinstance(v, list):
            raise TypeError("reasons must be a list")
        if not (1 <= len(v) <= 4):
            raise ValueError("reasons must contain 1–4 items")
        for r in v:
            if not isinstance(r, str) or not (4 <= len(r) <= 140):
                raise ValueError("each reason must be 4–140 chars")
        return v

    @validator("confidence")
    def _conf(cls, v):
        try:
            v = float(v)
        except Exception:
            raise TypeError("confidence must be a float")
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence out of range [0,1]")
        return v
