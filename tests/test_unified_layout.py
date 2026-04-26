from math import floor
from random import randint
import pytest
from rich.console import Console
from rich.text import Text

from kcd_gfx_toolbox.diff.core import DiffHunk, TextHunk, TextHunkLine
from kcd_gfx_toolbox.diff.unified_layout import UnifiedLayout


def _hunk_ctx(index: int, text: str) -> TextHunkLine:
    """Create a text hunk context line."""
    return TextHunkLine(index=index, text=text, is_context=True)


def _hunk_del(index: int, text: str) -> TextHunkLine:
    """Create a text hunk deletion line."""
    return TextHunkLine(index=index, text=text, is_deletion=True)


def _hunk_add(index: int, text: str) -> TextHunkLine:
    """Create a text hunk addition line."""
    return TextHunkLine(index=index, text=text, is_addition=True)


def _plain_lines(layout: UnifiedLayout) -> list[str]:
    """Return the layout lines as plain text, with Rich markup stripped."""
    return [str(line) for line in layout.lines]


def test_UnifiedLayout_rejects_both_sides_being_undefined():
    with pytest.raises(ValueError, match="At least one side must be defined"):
        UnifiedLayout(None, None, [])


def test_UnifiedLayout_emits_only_headers_when_there_are_no_hunk_pairs():
    layout = UnifiedLayout("foo:bar", "foo:bar", [])
    assert _plain_lines(layout) == [
        "--- a/foo:bar",
        "+++ b/foo:bar",
    ]


def test_UnifiedLayout_skips_pairs_where_both_sides_are_empty():
    layout = UnifiedLayout("foo:bar", "foo:bar", [(DiffHunk(), DiffHunk())])
    assert _plain_lines(layout) == [
        "--- a/foo:bar",
        "+++ b/foo:bar",
    ]


def test_UnifiedLayout_emits_at_at_with_absolute_block_indices():
    diffed_a = DiffHunk(
        [
            TextHunk([_hunk_ctx(8, "ctx0"), _hunk_ctx(9, "ctx1")]),
            TextHunk([_hunk_del(10, "old1"), _hunk_del(11, "old2")]),
            TextHunk([_hunk_ctx(12, "ctx2")]),
        ]
    )
    diffed_b = DiffHunk(
        [
            TextHunk([_hunk_ctx(20, "ctx0"), _hunk_ctx(21, "ctx1")]),
            TextHunk([_hunk_add(22, "new1")]),
            TextHunk([_hunk_ctx(23, "ctx2")]),
        ]
    )
    layout = UnifiedLayout("x:y", "x:y", [(diffed_a, diffed_b)])

    # Lines in A start at index 8, lines in B start at index 20: the hunk header must reflect that.
    # In other terms, they must not be relative to the hunk they are in.
    assert _plain_lines(layout) == [
        "--- a/x:y",
        "+++ b/x:y",
        "@@ -9,5 +21,4 @@",
        " ctx0",
        " ctx1",
        "-old1",
        "-old2",
        "+new1",
        " ctx2",
    ]


def test_UnifiedLayout_pure_insertion_uses_zero_zero_on_side_a():
    diffed_a = DiffHunk([TextHunk([])])
    diffed_b = DiffHunk([TextHunk([_hunk_add(4, "n1"), _hunk_add(5, "n2")])])
    layout = UnifiedLayout(None, "foo:bar", [(diffed_a, diffed_b)])

    assert _plain_lines(layout) == [
        "--- /dev/null",
        "+++ b/foo:bar",
        "@@ -0,0 +5,2 @@",
        "+n1",
        "+n2",
    ]


def test_UnifiedLayout_pure_deletion_uses_zero_zero_on_side_b():
    diffed_a = DiffHunk([TextHunk([_hunk_del(0, "o1"), _hunk_del(1, "o2")])])
    diffed_b = DiffHunk([TextHunk([])])
    layout = UnifiedLayout("foo:bar", None, [(diffed_a, diffed_b)])

    assert _plain_lines(layout) == [
        "--- a/foo:bar",
        "+++ /dev/null",
        "@@ -1,2 +0,0 @@",
        "-o1",
        "-o2",
    ]


def test_UnifiedLayout_escapes_rich_markup_in_line_text():
    # Lines with bracket characters must not be parsed as Rich markup.
    diffed_a = DiffHunk([TextHunk([_hunk_del(0, "[bold]hi[/bold]")]), TextHunk([_hunk_ctx(1, "[dim]bye[/dim]")])])
    diffed_b = DiffHunk([TextHunk([_hunk_add(0, "[red]bye[/red]")]), TextHunk([_hunk_ctx(1, "[dim]bye[/dim]")])])
    layout = UnifiedLayout("foo:bar", "foo:bar", [(diffed_a, diffed_b)])

    assert _plain_lines(layout) == [
        "--- a/foo:bar",
        "+++ b/foo:bar",
        "@@ -1,2 +1,2 @@",
        "-[bold]hi[/bold]",
        "+[red]bye[/red]",
        " [dim]bye[/dim]",
    ]


# Important: extend_factor must be > 1, max_width must not be absurdly low.
@pytest.mark.parametrize(
    "max_width,extend_factor", [(randint(80, 240), randint(1, 5) + randint(1, 9) / 10) for _ in range(5)]
)
def test_UnifiedLayout_compute_height_handles_word_wrap(max_width, extend_factor):
    diffed_a = DiffHunk([TextHunk([_hunk_del(0, "x" * (max_width - 1))])])
    diffed_b = DiffHunk([TextHunk([_hunk_add(0, "x" * floor(max_width * extend_factor))])])
    layout = UnifiedLayout("foo:bar", "foo:bar", [(diffed_a, diffed_b)])

    console = Console(width=max_width)
    # 2 headers + 1 @@ + 1 deletion line + an insertion line wrapping on 1 + floor(extend_factor) rows.
    assert layout.compute_height(console, max_width) == 5 + floor(extend_factor)


def test_UnifiedLayout_yields_text_objects_via_rich_console_protocol():
    diffed_a = DiffHunk([TextHunk([_hunk_del(0, "o")])])
    diffed_b = DiffHunk([TextHunk([_hunk_add(0, "n")])])
    layout = UnifiedLayout("foo:bar", "foo:bar", [(diffed_a, diffed_b)])

    console = Console(width=80)
    yielded = list(layout.__rich_console__(console, console.options))

    assert all(isinstance(item, Text) for item in yielded)
    # Must mirror the lines list, since we do not transform them and they would not wrap.
    assert [str(t) for t in yielded] == _plain_lines(layout)


def test_UnifiedLayout_caches_last_render_height_after_render():
    diffed_a = DiffHunk([TextHunk([_hunk_ctx(0, "x")])])
    diffed_b = DiffHunk([TextHunk([_hunk_ctx(0, "x")])])
    layout = UnifiedLayout("foo:bar", "foo:bar", [(diffed_a, diffed_b)])

    console = Console(width=80, record=True)
    console.print(layout)
    assert layout.get_last_render_height() == 4


def test_UnifiedLayout_prevents_calling_last_render_height_before_render():
    diffed_a = DiffHunk([TextHunk([_hunk_ctx(0, "x")])])
    diffed_b = DiffHunk([TextHunk([_hunk_ctx(0, "x")])])
    layout = UnifiedLayout("foo:bar", "foo:bar", [(diffed_a, diffed_b)])

    with pytest.raises(RuntimeError, match="Cannot call UnifiedLayout.get_last_render_height"):
        layout.get_last_render_height()
