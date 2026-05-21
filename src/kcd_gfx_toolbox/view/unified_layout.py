"""Unified diff rendering using Rich."""

from __future__ import annotations
from collections.abc import Iterator
from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

from kcd_gfx_toolbox.diff.core import DiffAnnotatedHunk
from kcd_gfx_toolbox.diff.unified_format import unidiff_file_diff


class UnifiedLayout:
    """Render a sequence of diffed hunk pairs as a unified diff format."""

    def __init__(
        self,
        side_a_path: str | None,
        side_b_path: str | None,
        hunk_pairs: list[tuple[DiffAnnotatedHunk, DiffAnnotatedHunk]],
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
        yield from unidiff_file_diff(self.side_a_path, self.side_b_path, self.hunk_pairs)

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
