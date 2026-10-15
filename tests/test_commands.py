from dataclasses import replace

from PySide6.QtGui import QUndoStack

from dimensio.commands import AddDimension, ChangeDimension, ChangeStyle, RemoveDimension
from dimensio.model import Dimension, Style


class FakeHost:
    def __init__(self):
        self.dims = []
        self.style = Style(2, 10)

    def insert_dimension(self, index, dim):
        self.dims.insert(index, dim)

    def remove_dimension(self, index):
        del self.dims[index]

    def replace_dimension(self, index, dim):
        self.dims[index] = dim

    def apply_style(self, style):
        self.style = style


def dim(label):
    return Dimension(((0.0, 0.0), (10.0, 0.0)), (label,))


def test_undo_redo_keeps_indexes_consistent_across_delete(qapp):
    host, stack = FakeHost(), QUndoStack()
    stack.push(AddDimension(host, 0, dim("a")))
    stack.push(AddDimension(host, 1, dim("b")))
    stack.push(RemoveDimension(host, 0, dim("a")))
    stack.push(ChangeDimension(host, 0, dim("b"), dim("c"), "Edit label"))
    assert host.dims == [dim("c")]
    stack.undo()
    assert host.dims == [dim("b")]
    stack.undo()
    assert host.dims == [dim("a"), dim("b")]
    stack.undo()
    assert host.dims == [dim("a")]
    for _ in range(3):
        stack.redo()
    assert host.dims == [dim("c")]


def test_style_changes_to_the_same_field_merge(qapp):
    host, stack = FakeHost(), QUndoStack()
    s0 = host.style
    stack.push(ChangeStyle(host, s0, replace(s0, line_width=3)))
    stack.push(ChangeStyle(host, replace(s0, line_width=3), replace(s0, line_width=4)))
    assert stack.count() == 1
    assert host.style.line_width == 4
    stack.undo()
    assert host.style == s0


def test_style_changes_to_different_fields_stay_separate(qapp):
    host, stack = FakeHost(), QUndoStack()
    s0 = host.style
    s1 = replace(s0, line_width=3)
    stack.push(ChangeStyle(host, s0, s1))
    stack.push(ChangeStyle(host, s1, replace(s1, color="#00FF00")))
    assert stack.count() == 2


def test_outline_toggle_is_its_own_undo_step(qapp):
    host, stack = FakeHost(), QUndoStack()
    s0 = host.style
    s1 = replace(s0, line_width=3)
    stack.push(ChangeStyle(host, s0, s1))
    stack.push(ChangeStyle(host, s1, replace(s1, outline=False)))
    assert stack.count() == 2
