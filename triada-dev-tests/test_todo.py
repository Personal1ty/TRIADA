import pytest
from todo import TodoList, TodoItem


class TestTodoListAdd:
    def test_add_returns_todoitem(self):
        todo_list = TodoList()
        item = todo_list.add("Buy milk")
        assert isinstance(item, TodoItem)
        assert item.title == "Buy milk"
        assert item.completed is False

    def test_add_increments_id(self):
        todo_list = TodoList()
        item1 = todo_list.add("Task 1")
        item2 = todo_list.add("Task 2")
        assert item1.id == 1
        assert item2.id == 2

    def test_add_empty_title_raises_value_error(self):
        todo_list = TodoList()
        with pytest.raises(ValueError, match="title cannot be empty or whitespace-only"):
            todo_list.add("")

    def test_add_whitespace_only_title_raises_value_error(self):
        todo_list = TodoList()
        with pytest.raises(ValueError, match="title cannot be empty or whitespace-only"):
            todo_list.add("   ")


class TestTodoListComplete:
    def test_complete_existing_task(self):
        todo_list = TodoList()
        item = todo_list.add("Finish report")
        completed_item = todo_list.complete(item.id)
        assert completed_item.completed is True
        assert todo_list._items[item.id].completed is True

    def test_complete_unknown_id_raises_key_error(self):
        todo_list = TodoList()
        with pytest.raises(KeyError):
            todo_list.complete(999)


class TestTodoListPending:
    def test_pending_returns_only_uncompleted_items(self):
        todo_list = TodoList()
        item1 = todo_list.add("A")
        item2 = todo_list.add("B")
        todo_list.complete(item1.id)
        pending = todo_list.pending()
        assert len(pending) == 1
        assert pending[0] == item2

    def test_pending_empty_when_all_completed(self):
        todo_list = TodoList()
        item = todo_list.add("Task")
        todo_list.complete(item.id)
        assert todo_list.pending() == []
