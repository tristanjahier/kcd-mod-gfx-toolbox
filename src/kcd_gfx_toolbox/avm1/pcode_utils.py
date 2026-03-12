import re

WORD_TOKEN = r"[a-zA-Z_][a-zA-Z\d_]*"
LABEL_PREFIXED_LINE_RE = re.compile(rf"^\s*(?P<prefix>(?P<label>{WORD_TOKEN})\s*:)\s*(?P<rest>.*)$")
LABEL_REFERENCED_LINE_RE = re.compile(rf"^(?P<opcode>If|Jump)\s+(?P<label>{WORD_TOKEN})$", flags=re.IGNORECASE)

REGISTER_REFERENCE_RE = re.compile(r"\bregister(?P<regindex>\d+)\b")
PUSH_REGISTER_RE = re.compile(rf"^\s*Push\s+.*(?P<register>{REGISTER_REFERENCE_RE.pattern}).*")
STORE_REGISTER_RE = re.compile(r"^\s*StoreRegister\s+(?P<regindex>\d+)\s*")


def extract_label_from_line(line: str) -> tuple[str, str | None]:
    """
    Extract the label of a p-code line if any. Return the rest of the line and the label.
    """
    if match := LABEL_PREFIXED_LINE_RE.match(line):
        return (match.group("rest"), match.group("label"))

    return (line, None)


def strip_label(line: str) -> str:
    """
    Remove the leading label if present (like `loc044b:` or `L12:`).
    """
    match = LABEL_PREFIXED_LINE_RE.match(line)
    return match.group("rest") if match else line
