"""Side-by-side diff rendering using Rich."""

from __future__ import annotations
from abc import ABC, abstractmethod
from itertools import chain, zip_longest
from math import ceil, floor
from typing import Self
from rich.console import Console, ConsoleOptions, RenderResult, RenderableType
from rich.padding import Padding, PaddingDimensions
from rich.style import Style
from rich.table import Table
from rich.text import Text
from pygments.lexer import Lexer
from pygments.style import Style as PygmentsStyle
from pygments.styles.material import MaterialStyle as DefaultPygmentStyle

from kcd_gfx_toolbox.diff.core import DiffAnnotatedHunk, TextHunkLine
from .syntax_highlighting import highlight_line


class SplitLayoutPane(ABC):
    @abstractmethod
    def compute_height(self, console: Console, pane_width: int) -> int: ...

    @abstractmethod
    def render(self, vertical_gap: int | None = None) -> RenderableType: ...


class SplitLayoutPairAlignablePane(SplitLayoutPane):
    @classmethod
    @abstractmethod
    def prerender_rows_in_pair(
        cls,
        left: SplitLayoutPairAlignablePane,
        right: SplitLayoutPairAlignablePane,
        console: Console,
        left_pane_width: int,
        right_pane_width: int,
    ) -> None: ...

    @abstractmethod
    def prerender_rows(self) -> None: ...


class SplitLayout:
    def __init__(self, left_pane: SplitLayoutPane, right_pane: SplitLayoutPane, spacing: int = 1):
        self.left_pane = left_pane
        self.right_pane = right_pane
        self.spacing = spacing
        self._last_render_height: int | None = None

    def get_last_render_height(self) -> int:
        if self._last_render_height is None:
            raise RuntimeError(
                f"Cannot call {self.__class__.__name__}.get_last_render_height before rendering the component."
            )

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

        if (
            isinstance(self.left_pane, SplitLayoutPairAlignablePane)
            and isinstance(self.right_pane, SplitLayoutPairAlignablePane)
            and type(self.left_pane) is type(self.right_pane)
        ):
            type(self.left_pane).prerender_rows_in_pair(
                self.left_pane, self.right_pane, console, left_pane_width, right_pane_width
            )
        else:
            if isinstance(self.left_pane, SplitLayoutPairAlignablePane):
                self.left_pane.prerender_rows()
            if isinstance(self.right_pane, SplitLayoutPairAlignablePane):
                self.right_pane.prerender_rows()

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

    @classmethod
    def from_pair(
        cls,
        left: DiffAnnotatedHunk | SplitLayoutMessagePane,
        right: DiffAnnotatedHunk | SplitLayoutMessagePane,
        **kwargs,
    ) -> Self:
        if not isinstance(left, SplitLayoutMessagePane):
            left_pane = SplitLayoutDiffPane(left, **kwargs)
        else:
            left_pane = left

        if not isinstance(right, SplitLayoutMessagePane):
            right_pane = SplitLayoutDiffPane(right, **kwargs)
        else:
            right_pane = right

        return cls(left_pane, right_pane)


class SplitLayoutTextLine:
    def __init__(self, gutter: Text | str, text: Text | str):
        self.gutter: Text = gutter if isinstance(gutter, Text) else Text(gutter)
        self.text: Text = text if isinstance(text, Text) else Text(text)


class SplitLayoutTextPane(SplitLayoutPairAlignablePane):
    def __init__(
        self,
        lines: list[SplitLayoutTextLine],
        background_color: str | None = "#17171a",
        padding: PaddingDimensions = (1, 1),
        word_wrap: bool = False,
        syntax_lexer: Lexer | None = None,
        pygments_style: type[PygmentsStyle] | None = None,
        alignment_filler_background_color: str | None = "#232326",
    ):
        self._segments: list[list[SplitLayoutTextLine]] = [lines]
        self.background_color = background_color
        self.padding = padding
        self.word_wrap = word_wrap
        self.syntax_lexer = syntax_lexer
        self.pygments_style: type[PygmentsStyle] = pygments_style or DefaultPygmentStyle
        self.alignment_filler_background_color = alignment_filler_background_color
        self.gutter_min_width: int = 5
        self.gutter_text_spacing: int = 3
        self._gutter_width_cache: int | None = None
        self._rows: list[tuple[Text, Text]] | None = None

    def _compute_gutter_width(self) -> int:
        """Maximum between min width and max length of gutter text."""
        if self._gutter_width_cache is not None:
            return self._gutter_width_cache

        self._gutter_width_cache = max(
            self.gutter_min_width,
            max((len(line.gutter) for line in chain.from_iterable(self._segments)), default=0),
        )

        return self._gutter_width_cache

    def compute_height(self, console: Console, pane_width: int) -> int:
        """Compute the component height for a given width."""
        top_padding, right_padding, bottom_padding, left_padding = Padding.unpack(self.padding)
        gutter_width = self._compute_gutter_width()

        assert self._rows is not None

        if self.word_wrap:
            # Approximate the width available for the text column.
            text_width = max(1, pane_width - left_padding - right_padding - gutter_width - self.gutter_text_spacing)

            content_height = 0
            for row in self._rows:
                # row[1] is the text cell.
                content_height += max(1, len(row[1].wrap(console, text_width, overflow="ellipsis")))
        else:
            content_height = len(self._rows)

        return content_height + top_padding + bottom_padding

    def _compute_line_height(self, line: SplitLayoutTextLine, console: Console, pane_width: int) -> int:
        """Compute the render height of a line for a given width."""
        if not self.word_wrap:
            return 1

        _, right_padding, _, left_padding = Padding.unpack(self.padding)
        gutter_width = self._compute_gutter_width()

        # Compute the width available for the text column.
        text_width = max(1, pane_width - left_padding - right_padding - gutter_width - self.gutter_text_spacing)

        return max(1, len(line.text.wrap(console, text_width, overflow="ellipsis")))

    def _render_line(self, line: SplitLayoutTextLine) -> tuple[Text, Text]:
        """Render a SplitLayoutTextLine into Rich table cells."""
        if self.syntax_lexer is not None:
            line_text = highlight_line(line.text, self.syntax_lexer, self.pygments_style)
        else:
            line_text = line.text.copy()

        return (line.gutter.copy(), line_text)

    def prerender_rows(self) -> None:
        rows = []

        for line in chain.from_iterable(self._segments):
            rows.append(self._render_line(line))

        self._rows = rows

    def _alignment_filler_row(self) -> tuple[Text, Text]:
        """Return a row to fill an alignment gap on the shorter side."""
        return (Text(""), Text("", style=Style(bgcolor=self.alignment_filler_background_color)))

    @classmethod
    def prerender_rows_in_pair(
        cls,
        left: SplitLayoutPairAlignablePane,
        right: SplitLayoutPairAlignablePane,
        console: Console,
        left_pane_width: int,
        right_pane_width: int,
    ) -> None:
        assert isinstance(left, SplitLayoutTextPane) and isinstance(right, SplitLayoutTextPane)

        left_rows = []
        right_rows = []

        for left_segment, right_segment in zip(left._segments, right._segments):
            for left_line, right_line in zip_longest(left_segment, right_segment):
                left_height = 0
                right_height = 0

                if left_line is not None:
                    left_rows.append(left._render_line(left_line))
                    left_height = left._compute_line_height(left_line, console, left_pane_width)

                if right_line is not None:
                    right_rows.append(right._render_line(right_line))
                    right_height = right._compute_line_height(right_line, console, right_pane_width)

                if left_height < right_height:
                    left_rows.extend(left._alignment_filler_row() for _ in range(right_height - left_height))

                if left_height > right_height:
                    right_rows.extend(right._alignment_filler_row() for _ in range(left_height - right_height))

        left._rows = left_rows
        right._rows = right_rows

    def render(self, vertical_gap: int | None = None) -> RenderableType:
        if self._rows is None:
            self.prerender_rows()

        assert self._rows is not None

        grid = Table.grid(expand=True, padding=(0, self.gutter_text_spacing), collapse_padding=True, pad_edge=False)
        grid.add_column("gutter", justify="right", min_width=self.gutter_min_width, style="dim")
        grid.add_column("line_text", ratio=1, no_wrap=(not self.word_wrap), overflow="ellipsis")

        if self.background_color is not None:
            bg_style = Style(bgcolor=self.background_color)
            grid.row_styles = [bg_style]
        else:
            bg_style = Style.null()

        for row in self._rows:
            grid.add_row(*row)

        if vertical_gap is not None:
            # If this pane is shorter than its sibling, append blank rows to align them visually.
            for _ in range(max(0, vertical_gap)):
                grid.add_row("", "")

        return Padding(grid, pad=self.padding, style=bg_style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.render()


class SplitLayoutDiffPane(SplitLayoutTextPane):
    def __init__(
        self,
        diffed_hunk: DiffAnnotatedHunk,
        *,
        addition_background_color: str | None = "#1D4E28",
        deletion_background_color: str | None = "#4E1D20",
        **kwargs,
    ):
        super().__init__([], **kwargs)
        self.addition_background_color = addition_background_color
        self.deletion_background_color = deletion_background_color
        self._segments = [[self._convert_text_hunk_line(line) for line in segment] for segment in diffed_hunk]

    def _convert_text_hunk_line(self, line: TextHunkLine) -> SplitLayoutTextLine:
        style = Style()

        if line.is_deletion:
            style += Style(bgcolor=self.deletion_background_color)
        elif line.is_addition:
            style += Style(bgcolor=self.addition_background_color)

        return SplitLayoutTextLine(gutter=str(line.number), text=Text(line.text, style=style))


class SplitLayoutMessagePane(SplitLayoutPane):
    def __init__(self, message: str, background_color: str | None = "#17171a", padding: PaddingDimensions = (1, 2)):
        self.message = message
        self.background_color = background_color
        self.padding = padding

    def compute_height(self, console: Console, pane_width: int) -> int:
        """Compute the component height for a given width."""
        top_padding, right_padding, bottom_padding, left_padding = Padding.unpack(self.padding)

        # Approximate the width available for the text.
        text_width = max(1, pane_width - left_padding - right_padding)
        content_height = max(1, len(Text.from_markup(self.message).wrap(console, text_width, overflow="fold")))

        return content_height + top_padding + bottom_padding

    def render(self, vertical_gap: int | None = None) -> RenderableType:
        grid = Table.grid(expand=True)
        grid.add_column("message", justify="center", overflow="fold")

        gap = max(0, vertical_gap or 0) / 2
        before_gap = floor(gap)
        after_gap = ceil(gap)
        for _ in range(before_gap):
            grid.add_row("")
        grid.add_row(self.message)
        for _ in range(after_gap):
            grid.add_row("")

        bg_style = f"on {self.background_color}" if self.background_color is not None else ""

        return Padding(grid, pad=self.padding, style=bg_style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.render()
