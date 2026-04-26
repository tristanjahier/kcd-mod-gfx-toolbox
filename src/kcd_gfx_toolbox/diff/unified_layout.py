"""Unified diff rendering using Rich."""

from __future__ import annotations
from collections.abc import Iterator
from rich.console import Console, ConsoleOptions, RenderResult
from rich.markup import escape
from rich.text import Text

from .core import DiffHunk
from .unified_format import (
    unidiff_context_line,
    unidiff_deletion_line,
    unidiff_file_header,
    unidiff_hunk_header,
    unidiff_insertion_line,
)


class UnifiedLayout:
    """Render a sequence of diffed hunk pairs as a unified diff format."""

    def __init__(
        self,
        side_a_path: str | None,
        side_b_path: str | None,
        hunk_pairs: list[tuple[DiffHunk, DiffHunk]],
    ):
        if side_a_path is None and side_b_path is None:
            raise ValueError("At least one side must be defined.")

        self.side_a_path = side_a_path
        self.side_b_path = side_b_path
        self.hunk_pairs = hunk_pairs
        self._lines: list[Text] = list(self._render_lines())  # pre-compute and cache
        self._last_render_height: int | None = None

    @property
    def lines(self) -> list[Text]:
        """The rendered lines as a list of Rich Text objects."""
        return self._lines

    def _render_lines(self) -> Iterator[Text]:
        """
        Yield diff lines in "unified format" as Rich Text objects.
        """
        yield Text.from_markup(f"[bold]{escape(unidiff_file_header(self.side_a_path, 'a'))}[/bold]")
        yield Text.from_markup(f"[bold]{escape(unidiff_file_header(self.side_b_path, 'b'))}[/bold]")

        for diffed_a, diffed_b in self.hunk_pairs:
            a_lines = diffed_a.lines()
            b_lines = diffed_b.lines()

            if not a_lines and not b_lines:
                continue

            # 1-based start indices, with the unified-diff convention of 0 when the side has no lines.
            a_start = a_lines[0].index + 1 if a_lines else 0
            b_start = b_lines[0].index + 1 if b_lines else 0
            hunk_header = unidiff_hunk_header(a_start, len(a_lines), b_start, len(b_lines))
            yield Text.from_markup(f"[cyan]{hunk_header}[/cyan]")

            # diff_text_hunks produces two DiffHunks of equal length whose segments are pairwise
            # aligned: either a shared-context segment (both sides equal) or a replace/insert/
            # delete segment (deletions on A, additions on B; one side may be an empty segment).
            for seg_a, seg_b in zip(diffed_a, diffed_b):
                is_context_seg = (seg_a and seg_a[0].is_context) or (seg_b and seg_b[0].is_context)

                if is_context_seg:
                    # Context lines are identical on both sides; emit only once.
                    for ln in seg_a:
                        yield Text(unidiff_context_line(ln.text))
                else:
                    for ln in seg_a:
                        yield Text.from_markup(f"[red]{escape(unidiff_deletion_line(ln.text))}[/red]")
                    for ln in seg_b:
                        yield Text.from_markup(f"[green]{escape(unidiff_insertion_line(ln.text))}[/green]")

    def compute_height(self, console: Console, width: int) -> int:
        """Compute the component height for a given max output width, accounting for word wrap."""
        return sum(max(1, len(ln.wrap(console, width))) for ln in self._lines)

    def get_last_render_height(self) -> int:
        if self._last_render_height is None:
            raise RuntimeError(
                f"Cannot call {self.__class__.__name__}.get_last_render_height before rendering the component."
            )

        return self._last_render_height

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        self._last_render_height = self.compute_height(console, options.max_width)

        for line in self._lines:
            yield line
