import re

WORD_TOKEN = r"[a-zA-Z_][a-zA-Z\d_]*"
LABEL_PREFIXED_LINE_RE = re.compile(rf"^\s*(?P<prefix>(?P<label>{WORD_TOKEN})\s*:)\s*(?P<rest>.*)$")
REGISTER_REFERENCE_RE = re.compile(r"\bregister(?P<regindex>\d+)\b")


def extract_label_from_line(line: str) -> tuple[str, str | None]:
    """
    Extract the label of a p-code line if any. Return the rest of the line and the label.
    """
    if match := LABEL_PREFIXED_LINE_RE.match(line):
        return (match.group("rest"), match.group("label"))

    return (line, None)
