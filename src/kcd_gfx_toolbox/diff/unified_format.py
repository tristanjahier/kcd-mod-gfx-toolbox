"""
A set of helpers to render diffs in the "unified format" (per GNU diffutils, Git-flavored).

See https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html.
"""

from typing import Literal


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
