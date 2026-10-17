"""Undo commands. Every change to a document goes through one of these."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QUndoCommand

from .model import KINDS, LAYER_FIELDS, Dimension, Style

STYLE_MERGE_ID = 1


class DocumentHost(Protocol):
    def insert_dimension(self, index: int, dim: Dimension) -> None: ...
    def remove_dimension(self, index: int) -> None: ...
    def replace_dimension(self, index: int, dim: Dimension) -> None: ...
    def apply_style(self, style: Style) -> None: ...


class AddDimension(QUndoCommand):
    def __init__(self, host: DocumentHost, index: int, dim: Dimension) -> None:
        super().__init__("Add dimension")
        self._host, self._index, self._dim = host, index, dim

    def redo(self) -> None:
        self._host.insert_dimension(self._index, self._dim)

    def undo(self) -> None:
        self._host.remove_dimension(self._index)


class RemoveDimension(QUndoCommand):
    def __init__(self, host: DocumentHost, index: int, dim: Dimension) -> None:
        super().__init__("Delete dimension")
        self._host, self._index, self._dim = host, index, dim

    def redo(self) -> None:
        self._host.remove_dimension(self._index)

    def undo(self) -> None:
        self._host.insert_dimension(self._index, self._dim)


class ChangeDimension(QUndoCommand):
    def __init__(self, host: DocumentHost, index: int, old: Dimension, new: Dimension, text: str) -> None:
        super().__init__(text)
        self._host, self._index, self._old, self._new = host, index, old, new

    def redo(self) -> None:
        self._host.replace_dimension(self._index, self._new)

    def undo(self) -> None:
        self._host.replace_dimension(self._index, self._old)


def _changed_fields(old: Style, new: Style) -> frozenset[str]:
    """What changed, per layer, so that e.g. two colour changes on different layers stay two undo steps."""
    fields = {f for f in ("text_size", "ids", "hidden") if getattr(old, f) != getattr(new, f)}
    for kind in KINDS:
        a, b = old.layer(kind), new.layer(kind)
        fields |= {f"{kind}.{f}" for f in LAYER_FIELDS if getattr(a, f) != getattr(b, f)}
    return frozenset(fields)


class ChangeStyle(QUndoCommand):
    def __init__(self, host: DocumentHost, old: Style, new: Style) -> None:
        super().__init__("Change style")
        self._host, self._old, self._new = host, old, new
        self._fields = _changed_fields(old, new)

    def id(self) -> int:
        return STYLE_MERGE_ID

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, ChangeStyle) or other._fields != self._fields:
            return False
        self._new = other._new
        return True

    def redo(self) -> None:
        self._host.apply_style(self._new)

    def undo(self) -> None:
        self._host.apply_style(self._old)
