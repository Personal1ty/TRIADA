import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import Note


class NoteStore:
    def __init__(self, path: str):
        self._path = Path(path)
        self._notes: dict[int, Note] = {}
        self._next_id: int = 1
        self._last_loaded = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._notes = {}
            self._next_id = 1
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in store file '{self._path}': {e}")

        if not isinstance(data, dict):
            raise ValueError(f"Store file '{self._path}' must contain a JSON object.")

        self._notes = {}
        self._next_id = 1

        for note_data in data.get("notes", []):
            try:
                note_id = int(note_data["id"])
                self._notes[note_id] = Note(
                    id=note_id,
                    title=note_data["title"],
                    body=note_data["body"],
                    tags=note_data.get("tags", []),
                    created_at=datetime.fromisoformat(note_data["created_at"]) if "created_at" in note_data else datetime.now()
                )
                self._next_id = max(self._next_id, note_id + 1)
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"Malformed note entry in store file: {e}")

        self._last_loaded = True

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "notes": [
                    {
                        "id": note.id,
                        "title": note.title,
                        "body": note.body,
                        "tags": note.tags,
                        "created_at": note.created_at.isoformat()
                    }
                    for note in sorted(self._notes.values(), key=lambda n: n.id)
                ]
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (OSError, TypeError) as e:
            raise ValueError(f"Failed to save store to '{self._path}': {e}")

    def add(self, title: str, body: str, tags: Optional[List[str]] = None) -> Note:
        if not title or title.strip() == "":
            raise ValueError("title cannot be empty or whitespace-only")
        if not body or body.strip() == "":
            raise ValueError("body cannot be empty or whitespace-only")
        note = Note(
            id=self._next_id,
            title=title,
            body=body,
            tags=tags or [],
            created_at=datetime.now()
        )
        self._notes[note.id] = note
        self._next_id += 1
        self._save()
        return note

    def update(self, note_id: int, title: Optional[str] = None, body: Optional[str] = None, tags: Optional[List[str]] = None) -> Note:
        if note_id not in self._notes:
            raise KeyError(f"Note with id {note_id} not found")
        note = self._notes[note_id]
        if title is not None:
            if not title or title.strip() == "":
                raise ValueError("title cannot be empty or whitespace-only")
            note.title = title
        if body is not None:
            if not body or body.strip() == "":
                raise ValueError("body cannot be empty or whitespace-only")
            note.body = body
        if tags is not None:
            note.tags = tags
        self._save()
        return note

    def search(self, query: str) -> List[Note]:
        query_lower = query.lower()
        return [
            note for note in self._notes.values()
            if query_lower in note.title.lower()
            or query_lower in note.body.lower()
            or any(query_lower in tag.lower() for tag in note.tags)
        ]

    def list_notes(self) -> List[Note]:
        return [note for note in sorted(self._notes.values(), key=lambda n: n.id)]

    def save(self) -> None:
        self._save()

    def load(self) -> None:
        self._load()
