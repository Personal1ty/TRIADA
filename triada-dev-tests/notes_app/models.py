from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Note:
    id: int
    title: str
    body: str
    tags: List[str]
    created_at: datetime