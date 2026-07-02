from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class SceneRequest:
    book_id: str
    chapter_id: str
    year: int
    event_id: str
    event_name: str
    guardian: str
    location: str
    scene_type: str
    tone: str
    time_window: str
    pov: str
    characters_present: List[str] = field(default_factory=list)

@dataclass
class SceneRecord:
    scene_id: str
    book_id: str
    chapter_id: str
    title: str
    event_id: str
    event_name: str
    year: int
    guardian: str
    location: str
    scene_type: str
    time_window: str
    tone: str
    pov: str
    characters_present: List[str]
    status: str
    parent_scene_id: Optional[str] = None
    continued_from_scene_id: Optional[str] = None
    summary: str = ""
    tags: List[str] = field(default_factory=list)