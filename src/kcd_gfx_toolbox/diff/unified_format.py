"""
A set of helpers to render diffs in the "unified format" (per GNU diffutils, Git-flavored).

See https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html.
"""

from collections.abc import Iterator
from typing import Literal
from rich.markup import escape
from rich.text import Text

from .core import DiffAnnotatedHunk


def unidiff_file_diff(
    side_a_path: str | None,
    side_b_path: str | None,
    hunk_pairs: list[tuple[DiffAnnotatedHunk, DiffAnnotatedHunk]],
) -> Iterator[Text]:
    """
    Yield diff lines in "unified format" for a single file.

    Each line is a Rich Text object, formatted to appear as a git diff in the terminal.
    If the file was created, `side_a_path` should be None.
    If the file was deleted, `side_b_path` should be None.
    """
    if side_a_path is None and side_b_path is None:
        raise ValueError("At least one side must be defined.")

    yield Text.from_markup(f"[bold]{escape(unidiff_file_header(side_a_path, 'a'))}[/bold]")
    yield Text.from_markup(f"[bold]{escape(unidiff_file_header(side_b_path, 'b'))}[/bold]")

    for diffed_a, diffed_b in hunk_pairs:
        a_lines = diffed_a.lines()
        b_lines = diffed_b.lines()

        if not a_lines and not b_lines:
            continue

        # 1-based start indices, with the unified-diff convention of 0 when the side has no lines.
        a_start = a_lines[0].number if a_lines else 0
        b_start = b_lines[0].number if b_lines else 0
        hunk_header = unidiff_hunk_header(a_start, len(a_lines), b_start, len(b_lines))
        yield Text.from_markup(f"[cyan]{hunk_header}[/cyan]")

        # diff_text_hunks produces two DiffAnnotatedHunk of equal length whose segments are pairwise
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


def unidiff_file_header(path: str | None, side: Literal["a", "b"]) -> str:
    """
    Format a single file header: `--- a/...` or `+++ b/...` or `/dev/null` when missing.

    Formatting is Git-flavored.
    """
    if side == "a":
        marker = "---"
    elif side == "b":
        marker = "+++"
    else:
        raise ValueError(f"Invalid side {side!r}: must be 'a' or 'b'.")

    if path is None:
        return f"{marker} /dev/null"

    return f"{marker} {side}/{path}"


def unidiff_hunk_header(a_start: int, a_length: int, b_start: int, b_length: int) -> str:
    """Generate a unified format hunk header like `@@ -469,11 +470,21 @@`."""
    return f"@@ -{a_start},{a_length} +{b_start},{b_length} @@"


def unidiff_deletion_line(line: str) -> str:
    """Format a single line of text as a deletion line."""
    return "-" + line


def unidiff_insertion_line(line: str) -> str:
    """Format a single line of text as an insertion line."""
    return "+" + line


def unidiff_context_line(line: str) -> str:
    """Format a single line of text as a context line."""
    return " " + line
