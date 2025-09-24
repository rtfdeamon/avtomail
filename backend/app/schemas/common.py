from __future__ import annotations

from pydantic import BaseModel


class ORMModel(BaseModel):
    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }
