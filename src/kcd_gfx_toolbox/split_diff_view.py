from __future__ import annotations
from abc import ABC, abstractmethod
from math import ceil, floor
from typing import Self
from rich.console import Console, ConsoleOptions, RenderResult, RenderableType
from rich.padding import Padding, PaddingDimensions
from rich.table import Table
from rich.text import Text
from pygments.lexer import Lexer
from pygments.style import Style as PygmentsStyle
from pygments.styles.material import MaterialStyle as DefaultPygmentStyle
from pygments import lex as pygments_lex

from .file_diff import TextHunk


def _highlight_line(line: str, lexer: Lexer, pygments_style: type[PygmentsStyle]) -> Text:
    """
    Tokenize a line of source code with Pygments and return a rich.Text with syntax highlighting.
    The trailing newline appended by Pygments is stripped.
    """
    rich_text = Text()

    for token_type, value in pygments_lex(line, lexer):
        value = value.rstrip("\n")

        if not value:
            continue

        style_dict = pygments_style.style_for_token(token_type)
        rich_styles = []

        if color := style_dict.get("color"):
            rich_styles.append(f"#{color}")
        if style_dict.get("bold"):
            rich_styles.append("bold")
        if style_dict.get("italic"):
            rich_styles.append("italic")
        if style_dict.get("underline"):
            rich_styles.append("underline")

        rich_text.append(value, style=" ".join(rich_styles))

    return rich_text


class SplitDiffViewPane(ABC):
    @abstractmethod
    def compute_height(self, console: Console, pane_width: int) -> int: ...

    @abstractmethod
    def render(self, vertical_gap: int | None = None) -> RenderableType: ...


class SplitDiffView:
    def __init__(self, left_pane: SplitDiffViewPane, right_pane: SplitDiffViewPane, spacing: int = 1):
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
        left: TextHunk | SplitDiffViewMessagePane,
        right: TextHunk | SplitDiffViewMessagePane,
        **kwargs,
    ) -> Self:
        if not isinstance(left, SplitDiffViewMessagePane):
            left_pane = SplitDiffViewCodePane(left, **kwargs)
        else:
            left_pane = left

        if not isinstance(right, SplitDiffViewMessagePane):
            right_pane = SplitDiffViewCodePane(right, **kwargs)
        else:
            right_pane = right

        return cls(left_pane, right_pane)


class SplitDiffViewCodePane(SplitDiffViewPane):
    def __init__(
        self,
        text_hunk: TextHunk,
        background_color: str | None = "#17171a",
        padding: PaddingDimensions = (1, 1),
        word_wrap: bool = False,
        syntax_lexer: Lexer | None = None,
        pygments_style: type[PygmentsStyle] | None = None,
    ):
        self.text_hunk = text_hunk
        self.background_color = background_color
        self.padding = padding
        self.word_wrap = word_wrap
        self.syntax_lexer = syntax_lexer
        self.pygments_style: type[PygmentsStyle] = pygments_style or DefaultPygmentStyle
        self.gutter_min_width: int = 5
        self.gutter_text_spacing: int = 3

    def compute_height(self, console: Console, pane_width: int) -> int:
        """Compute the component height for a given width."""
        top_padding, right_padding, bottom_padding, left_padding = Padding.unpack(self.padding)

        # Max between min width and length of the biggest line number.
        gutter_width = max(
            self.gutter_min_width,
            max((len(str(line.index)) for line in self.text_hunk), default=0),
        )

        if self.word_wrap:
            # Approximate the width available for the text column.
            text_width = max(1, pane_width - left_padding - right_padding - gutter_width - self.gutter_text_spacing)

            content_height = 0
            for line in self.text_hunk:
                content_height += max(1, len(Text(line.text).wrap(console, text_width, overflow="ellipsis")))
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

        for line in self.text_hunk:
            if self.syntax_lexer is not None:
                text = _highlight_line(line.text, self.syntax_lexer, self.pygments_style)
            else:
                text = Text(line.text)

            text.style = "dim" if line.is_context else "bold"

            grid.add_row(str(line.index), text)

        if vertical_gap is not None:
            for _ in range(max(0, vertical_gap)):
                grid.add_row("", "")

        return Padding(grid, pad=self.padding, style=bg_style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.render()


class SplitDiffViewMessagePane(SplitDiffViewPane):
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
