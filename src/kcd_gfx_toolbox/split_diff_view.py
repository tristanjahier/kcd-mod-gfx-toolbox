from __future__ import annotations
from math import ceil, floor
from rich.console import Console, ConsoleOptions, RenderResult, RenderableType
from rich.padding import Padding, PaddingDimensions
from rich.table import Table
from rich.text import Text

from .file_diff import TextHunk


class SplitDiffView:
    def __init__(self, left_pane: SplitDiffViewPane, right_pane: SplitDiffViewPane, spacing: int = 1):
        self.left_pane = left_pane
        self.right_pane = right_pane
        self.spacing = spacing
        self._last_render_height: int | None = None

    def get_last_render_height(self) -> int:
        if self._last_render_height is None:
            raise RuntimeError(f"Cannot call {self.__class__.__name__}.get_last_render_height before rendering the component.")

        return self._last_render_height

    def _compute_pane_widths(self, total_width: int) -> tuple[int, int]:
        width = (total_width - self.spacing) / 2
        return ceil(width), floor(width)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        grid = Table.grid(expand=True)
        grid.add_column("pane_a", ratio=1)
        # Using a fixed-width column makes the layout computation more predictable than cell padding.
        grid.add_column("gap", width=self.spacing)
        grid.add_column("pane_b", ratio=1)

        left_pane_width, right_pane_width = self._compute_pane_widths(options.max_width)
        left_height = self.left_pane.compute_height(console, left_pane_width)
        right_height = self.right_pane.compute_height(console, right_pane_width)
        target_height = max(left_height, right_height)
        grid.add_row(
            self.left_pane.render(target_height - left_height),
            None,
            self.right_pane.render(target_height - right_height),
        )

        self._last_render_height = target_height

        yield grid


class SplitDiffViewPane:
    def __init__(
        self,
        text_hunk: TextHunk,
        highlighted_lines: set[int] | None = None,
        background_color: str | None = "#17171a",
        padding: PaddingDimensions = (1, 1),
        word_wrap: bool = False,
    ):
        self.text_hunk = text_hunk
        self.highlighted_lines = highlighted_lines or set()
        self.background_color = background_color
        self.padding = padding
        self.word_wrap = word_wrap
        self.gutter_min_width: int = 5
        self.gutter_text_spacing: int = 3

    def compute_height(self, console: Console, pane_width: int) -> int:
        """Compute the component height for a given width."""
        top_padding, right_padding, bottom_padding, left_padding = Padding.unpack(self.padding)

        # Max between min width and length of the biggest line number.
        gutter_width = max(
            self.gutter_min_width,
            max((len(str(ln)) for ln, _ in self.text_hunk if ln is not None), default=0),
        )

        if self.word_wrap:
            # Approximate the width available for the text column.
            text_width = max(1, pane_width - left_padding - right_padding - gutter_width - self.gutter_text_spacing)

            content_height = 0
            for _, txt in self.text_hunk:
                content_height += max(1, len(Text(txt).wrap(console, text_width, overflow="ellipsis")))
        else:
            content_height = len(self.text_hunk)

        return content_height + top_padding + bottom_padding

    def render(self, vertical_gap: int | None = None) -> RenderableType:
        bg_style = f"on {self.background_color}" if self.background_color is not None else ""

        grid = Table.grid(expand=True, padding=(0, self.gutter_text_spacing), collapse_padding=True, pad_edge=False)

        # A sensible minimum width helps keep consecutive split diff views aligned.
        grid.add_column("gutter", justify="right", min_width=self.gutter_min_width, style="dim")

        grid.add_column("line_text", ratio=1, no_wrap=(not self.word_wrap), overflow="ellipsis")

        if self.background_color:
            grid.row_styles = [bg_style]

        line_highlighting = bool(self.highlighted_lines)

        for ln, text in self.text_hunk:
            if ln is None:
                ln = ""
            elif line_highlighting:
                if ln in self.highlighted_lines:
                    style = "bold"
                else:
                    style = "dim"
                text = Text(text, style=style)

            grid.add_row(str(ln), text)

        if vertical_gap is not None:
            for _ in range(max(0, vertical_gap)):
                grid.add_row("", "")

        return Padding(grid, pad=self.padding, style=bg_style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.render()
