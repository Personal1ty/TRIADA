import json
import os
import tempfile
from datetime import datetime

import pytest

from notes_app.models import Note
from notes_app.store import NoteStore


class TestNoteStoreAdd:
    def test_add_creates_note_with_incrementing_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "store.json")
            store = NoteStore(store_path)
            note1 = store.add("Title 1", "Body 1", ["tag1"])
            note2 = store.add("Title 2", "Body 2")
            assert note1.id == 1
            assert note2.id == 2
            assert note1.title == "Title 1"
            assert note2.title == "Title 2"
            assert note1.body == "Body 1"
            assert note2.body == "Body 2"
            assert note1.tags == ["tag1"]
            assert note2.tags == []
            assert isinstance(note1.created_at, datetime)
            assert isinstance(note2.created_at, datetime)

    def test_add_empty_title_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            with pytest.raises(ValueError, match="title cannot be empty"):
                store.add("", "Body")
            with pytest.raises(ValueError, match="title cannot be empty"):
                store.add("   ", "Body")

    def test_add_empty_body_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            with pytest.raises(ValueError, match="body cannot be empty"):
                store.add("Title", "")
            with pytest.raises(ValueError, match="body cannot be empty"):
                store.add("Title", "   ")


class TestNoteStoreUpdate:
    def test_update_changes_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            note = store.add("Old title", "Old body", ["old"])
            updated = store.update(note.id, title="New title", body="New body", tags=["new"])
            assert updated.id == note.id
            assert updated.title == "New title"
            assert updated.body == "New body"
            assert updated.tags == ["new"]

    def test_update_unknown_id_raises_key_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            with pytest.raises(KeyError, match="not found"):
                store.update(999, title="New")


class TestNoteStoreSearch:
    def test_search_by_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            store.add("Important task", "Description", ["work"])
            store.add("Grocery list", "Milk, eggs", ["home"])
            results = store.search("important")
            assert len(results) == 1
            assert results[0].title == "Important task"

    def test_search_by_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            store.add("Title", "Remember to buy milk")
            results = store.search("milk")
            assert len(results) == 1

    def test_search_by_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = NoteStore(os.path.join(tmpdir, "store.json"))
            store.add("Title", "Body", ["project", "urgent"])
            store.add("Another", "Body", ["todo"])
            results = store.search("URGENT")
            assert len(results) == 1
            assert "urgent" in results[0].tags


class TestNoteStorePersistence:
    def test_save_and_load_survives_new_instance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "store.json")
            store = NoteStore(store_path)
            note1 = store.add("Note 1", "Body 1")
            note2 = store.add("Note 2", "Body 2", ["tag"])
            new_store = NoteStore(store_path)
            notes = new_store.list_notes()
            assert len(notes) == 2
            assert notes[0].id == 1
            assert notes[1].id == 2
            assert notes[0].title == "Note 1"
            assert notes[1].tags == ["tag"]

    def test_load_missing_file_creates_empty_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "new_store.json")
            store = NoteStore(store_path)
            assert store.list_notes() == []


class TestNoteStoreCorruptedJSON:
    def test_load_corrupted_json_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "corrupted.json")
            with open(store_path, "w") as f:
                f.write("{ invalid json }")
            with pytest.raises(ValueError, match="Invalid JSON"):
                NoteStore(store_path)

    def test_load_json_with_malformed_note_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "bad_note.json")
            with open(store_path, "w") as f:
                json.dump({"notes": [{"id": "not_an_int", "title": "T", "body": "B"}]}, f)
            with pytest.raises(ValueError, match="Malformed note"):
                NoteStore(store_path)


class TestIntegration:
    def test_full_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "workflow.json")
            # Create notes
            store = NoteStore(store_path)
            n1 = store.add("First", "Content 1", ["tagA"])
            n2 = store.add("Second", "Content 2", ["tagB"])
            # Save and load
            store.save()
            store2 = NoteStore(store_path)
            # Update one note
            updated = store2.update(n2.id, title="Updated Second")
            assert updated.title == "Updated Second"
            # Search
            found = store2.search("tagb")
            assert len(found) == 1
            assert found[0].id == n2.id
            # List notes (ordered by id)
            notes = store2.list_notes()
            assert [n.id for n in notes] == [1, 2]
