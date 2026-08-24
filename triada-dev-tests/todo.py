import dataclasses
from dataclasses import dataclass


@dataclass
class TodoItem:
    id: int
    title: str
    completed: bool = False


class TodoList:
    def __init__(self):
        self._items: dict[int, TodoItem] = {}
        self._next_id: int = 1

    def add(self, title: str) -> TodoItem:
        if not title or title.strip() == "":
            raise ValueError("title cannot be empty or whitespace-only")
        item = TodoItem(id=self._next_id, title=title, completed=False)
        self._items[self._next_id] = item
        self._next_id += 1
        return item

    def complete(self, item_id: int) -> TodoItem:
        if item_id not in self._items:
            raise KeyError(f"TodoItem with id {item_id} not found")
        item = self._items[item_id]
        new_item = dataclasses.replace(item, completed=True)
        self._items[item_id] = new_item
        return new_item

    def pending(self) -> list[TodoItem]:
        return [item for item in self._items.values() if not item.completed]
