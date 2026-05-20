from pygments import lex as pygments_lex
from pygments.lexer import Lexer
from pygments.style import Style as PygmentsStyle
from rich.text import Text


def highlight_line(line: Text | str, lexer: Lexer, pygments_style: type[PygmentsStyle]) -> Text:
    """
    Tokenize a line of source code with Pygments and return a rich.Text with syntax highlighting.
    The trailing newline appended by Pygments is stripped.
    """
    if isinstance(line, Text):
        highlighted_line = line.blank_copy()  # keep original style and formatting
    else:
        highlighted_line = Text()

    for token_type, value in pygments_lex(str(line), lexer):
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

        highlighted_line.append(value, style=" ".join(rich_styles))

    return highlighted_line
