# notes_app

A minimal notes application library with in-memory and JSON-backed persistence.

## Public API

### Note (dataclass)

- `id: int` — unique identifier
- `title: str` — note title
- `body: str` — note body
- `tags: List[str]` — list of tags
- `created_at: datetime.datetime` — creation timestamp (auto-populated)

### NoteStore(path: str)

Manages persistent storage of notes in JSON format.

#### Constructor

- `NoteStore(path)` — loads existing store or creates new if file missing. Raises `ValueError` on corrupted JSON.

#### Methods

- `add(title: str, body: str, tags: List[str] = []) -> Note` — creates note with auto-incrementing ID. Raises `ValueError` for empty title/body.
- `update(note_id: int, title: Optional[str] = None, body: Optional[str] = None, tags: Optional[List[str]] = None) -> Note` — updates fields. Raises `KeyError` if note_id not found.
- `search(query: str) -> List[Note]` — case-insensitive search in title, body, and tags.
- `list_notes() -> List[Note]` — returns notes ordered by ascending id.
- `save()` — persists current state to file.
- `load()` — reloads from file, discarding in-memory changes.

## JSON Format

Notes are stored in a JSON object with key `notes`, an array of note objects:

```json
{
  "notes": [
    {
      "id": 1,
      "title": "Buy milk",
      "body": "Need 2% milk for coffee",
      "tags": ["groceries", "urgent"],
      "created_at": "2025-01-01T12:00:00"
    }
  ]
}
```

- `id`: integer, used for ordering and reference
- `created_at`: ISO 8601 datetime string
- Tags are represented as a JSON array of strings

Errors

- If the store file does not exist, an empty store is assumed.
- If the JSON is invalid or contains malformed note entries, `ValueError` is raised with a descriptive message.