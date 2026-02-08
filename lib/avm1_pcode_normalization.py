from pathlib import Path
import re
from dataclasses import dataclass
from lib.util import safe_filename

LABEL_PREFIX_RE = re.compile(r'^\s*(?:loc[0-9a-fA-F]+|L\d+)\s*:\s*(.*)$')
LABEL_RE = re.compile(r"\b(?:loc[0-9a-fA-F]+|L\d+)\b")
LABEL_NAME_RE = re.compile(r"^(?:loc[0-9a-fA-F]+|L\d+)$")
DOT0_RE = re.compile(r"\b(-?\d+)\.0\b")  # 0.0, 1.0, 5.0...
NEG0_RE = re.compile(r"\b-0\b") # -0

REGISTER_RE = re.compile(r"\b(?:register|r)(\d+)\b")
STORE_REGISTER_RE = re.compile(r'\bStoreRegister\s+(?:register|r)?(\d+)\b')

PUSH_SINGLE_RE = re.compile(r'^\s*Push\s+(?:register\d+|r\d+)\s*,\s*"([^"]+)"\s*$')
PUSH_OBJ_RE = re.compile(r'^\s*Push\s+(?:register\d+|r\d+)\s*$')
PUSH_NAME_RE = re.compile(r'^\s*Push\s+"([^"]+)"\s*$')

DEFINE_FUNCTION_ANY_RE = re.compile(r'^\s*DefineFunction(?:2)?\b')
DEFINE_FUNCTION2_RE = re.compile(r'^\s*DefineFunction2\b')
DEFINE_FUNCTION2_REGCOUNT_RE = re.compile(r'^(?P<head>\s*DefineFunction2\s+"[^"]*"\s*,\s*\d+\s*,\s*)\d+(?P<tail>\s*,.*)$')
DEFINE_FUNCTION_HEADER_RE = re.compile(r'^\s*DefineFunction(?:2)?\s*"([^"]*)"\s*,\s*(\d+)')

def strip_label(line: str) -> str:
    """
    Remove the leading label if present (like `loc044b:` or `L12:`).
    """
    match = LABEL_PREFIX_RE.match(line)
    return match.group(1) if match else line

def find_function_name_and_start_line(
    lines: list[str],
    define_function_idx: int,
    max_lookback: int = 64
) -> tuple[int, str] | None:
    """
    For a function definition keyword found at line `define_function_idx`,
    look back for a member-binding pattern, which can be either:
        a. Push <reg>, "Name"
        b. Push <reg>
           Push "Name"

    Return the start index and the function name if found, else None.
    """
    i0 = max(0, define_function_idx - max_lookback) # lower bound of the lookback window

    # We scan the text backwards from the line of the function definition keyword.
    for i in range(define_function_idx - 1, i0 - 1, -1):
        line = strip_label(lines[i]).strip()

        # Found: Push <reg>, "Name"
        if match := PUSH_SINGLE_RE.match(line):
            return (i, match.group(1))

        # Found: Push "Name" and there is at least one more line before.
        if (match := PUSH_NAME_RE.match(line)) and i - 1 >= 0:
            prev = strip_label(lines[i - 1]).strip()
            if PUSH_OBJ_RE.match(prev):
                return (i - 1, match.group(1))

    return None

def find_function_end_line(lines: list[str], define_function_idx: int) -> int:
    """
    Find the index of the line closing the function that starts at `define_function_idx`.
    Use brace-depth tracking to avoid stopping at nested function boundaries.
    Fall back to last line if no closing brace was found.
    """
    depth = 0
    opening_seen = False

    for i in range(define_function_idx, len(lines)):
        line = strip_label(lines[i]).strip()
        openings = line.count("{")
        closings = line.count("}")

        if openings > 0:
            opening_seen = True

        depth += openings - closings

        # `opening_seen == True` means that we have entered the function body.
        # `depth <= 0` means we've closed it.
        if opening_seen and depth <= 0:
            return i

    return len(lines) - 1 # Fallback; should never happen with well-formed p-code.

def split_into_blocks(pcode_text: str) -> list[tuple[str, list[str]]]:
    """
    Splits a p-code text into a sequence of blocks:
    - Function blocks: named from method binding when found, otherwise `__anonymous`. A function block includes:
        - optional binding `Push` line(s),
        - the `DefineFunction`/`DefineFunction2` body,
        - a trailing `SetMember` when present.
    - Top-level gap blocks between or around function blocks (for example, class property initialization).
    """
    lines = pcode_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()

    blocks: list[tuple[str, list[str]]] = []
    name_occurrences: dict[str, int] = {}

    def add_block(name: str, a: int, b: int):
        """Add a block only if it is not blank"""
        seg = lines[a:b]
        if any(ln.strip() for ln in seg):
            blocks.append((name, seg))

    i = 0
    next_gap_start = 0

    while i < len(lines):
        current = strip_label(lines[i]).strip()

        # If we find a function definition keyword.
        if DEFINE_FUNCTION_ANY_RE.match(current):
            func_info = find_function_name_and_start_line(lines, i)

            if func_info:
                start, func_name = func_info
            else:
                start, func_name = i, "__anonymous"

            # The following condition should never happen with well-formed p-code.
            # However, in case of a lookup failure, at least we avoid overlapping blocks.
            if start < next_gap_start:
                start = next_gap_start

            # We need to register the "gap" that we passed between this function block and the previous one, if any.
            if next_gap_start < start:
                add_block("__toplevel", next_gap_start, start)

            # Find the end of the function body.
            end = find_function_end_line(lines, i)

            # Include trailing SetMember if present on the next line.
            if (end + 1) < len(lines) and strip_label(lines[end + 1]).strip() == "SetMember":
                end += 1

            block_name = safe_filename(func_name)
            if not block_name:
                block_name = "__anonymous"

            count = name_occurrences.get(block_name, 0)
            name_occurrences[block_name] = count + 1

            if count > 0:
                block_name = f"{block_name}__{count+1}"

            add_block(block_name, start, end + 1)

            # Jump straight to the next line after the function block.
            i = end + 1
            next_gap_start = i
            continue

        i += 1

    # Finally we need to register the gap that might exist between the last function and the end of the file.
    if next_gap_start < len(lines):
        add_block("__toplevel", next_gap_start, len(lines))

    return blocks

def split_comma_separated_operands(s: str) -> list[str]:
    """
    Split a comma-separated operand line while ignoring commas inside quotes.

    Backslash escaping is honored while scanning quoted text.
    Returned parts are stripped, and empty parts are omitted.

    Example:
        r0, "cagada, ahah"
    =>
        r0
        "cagada, ahah"
    """
    operands = []
    buffer = [] # characters encountered before a comma
    quoting = False
    escaping = False

    for char in s:
        if escaping:
            buffer.append(char)
            escaping = False
            continue
        if char == "\\":
            buffer.append(char)
            escaping = True
            continue
        if char == '"':
            buffer.append(char)
            quoting = not quoting
            continue
        if char == "," and not quoting:
            op = "".join(buffer).strip()
            if op:
                operands.append(op)
            buffer = [] # we just met a comma, so we reset the buffer
            continue
        buffer.append(char)

    if op := "".join(buffer).strip():
        operands.append(op)

    return operands

def extract_label_from_line(line: str) -> tuple[str, str | None]:
    """
    Extract the label of a p-code line if any. Return the rest of the line and the label.
    """
    if ":" in line:
        label, rest = line.split(":", 1)
        label = label.strip()
        if LABEL_NAME_RE.fullmatch(label):
            return (rest.lstrip(), label)

    return (line, None)

def canonicalize_push_lines(lines: list[str]) -> list[str]:
    """
    Canonicalize "Push" lines with multiple operands into single-operand "Push" lines.

    Example:
        Push r0, "GetWeight"
    =>
        Push r0

        Push "GetWeight"

    Preserve the label on the first line if present.
    """
    canonicalized_lines: list[str] = []

    for line in lines:
        # Put aside the label if present.
        labelless_line, label = extract_label_from_line(line)

        if labelless_line.startswith("Push "):
            operands = split_comma_separated_operands(labelless_line[len("Push "):])
            if len(operands) > 1:
                # Put back the label on the first line only, if it was present.
                label_prefix = label + ":" if label else ""
                canonicalized_lines.append(f"{label_prefix}Push {operands[0]}")

                for op in operands[1:]:
                    canonicalized_lines.append(f"Push {op}")
                continue

        canonicalized_lines.append(line)

    return canonicalized_lines

def canonicalize_number_literals(lines: list[str]) -> list[str]:
    """
    Canonicalize numbers to their simplest form.
    Examples:
        0.0 -> 0  |  1.0 -> 1  |  -0 -> 0  |  -8.0 -> -8
    """
    canonicalized_lines: list[str] = []

    for line in lines:
        line = DOT0_RE.sub(r"\1", line)
        line = NEG0_RE.sub("0", line)

        canonicalized_lines.append(line)

    return canonicalized_lines

def neutralize_definefunction2_register_operands(line: str) -> str:
    """
    Replace `DefineFunction2` register-related numeric operands with `N`.
    Example: `DefineFunction2 "<name>", <argc>, <register count>, ..., <reg>, "<arg>"`
    """
    # Put aside the label if present.
    labelless_line, label = extract_label_from_line(line)

    if not (match := DEFINE_FUNCTION2_REGCOUNT_RE.match(labelless_line)):
        return line

    # Put back the label if it was present.
    label_prefix = label + ":" if label else ""

    line = f"{label_prefix}{match.group('head')}N{match.group('tail')}"

    return re.sub(r',\s*\d+\s*,\s*"([^"]+)"', r', N, "\1"', line)

def canonicalize_definefunction_header_line(line: str) -> str:
    """
    Canonicalize DefineFunction/DefineFunction2 headers to one normalized form:
    Example: `DefineFunction "<name>", <argc>, "<arg1>", ... {`
    """
    # Put aside the label if present.
    labelless_line, label = extract_label_from_line(line)

    if not DEFINE_FUNCTION_ANY_RE.match(labelless_line):
        return line

    if not (match := DEFINE_FUNCTION_HEADER_RE.match(labelless_line)):
        return line

    func_name = match.group(1)
    argc = int(match.group(2))
    quoted_operands = re.findall(r'"([^"]*)"', labelless_line)
    arg_names = quoted_operands[1:1 + argc]

    normalized_line = f"DefineFunction \"{func_name}\", {argc}"
    for arg in arg_names:
        normalized_line += f', "{arg}"'
    normalized_line += " {"

    # Put back the label if it was present.
    label_prefix = label + ":" if label else ""

    return f"{label_prefix}{normalized_line}"

def canonicalize_function_definition_headers(lines: list[str]) -> list[str]:
    """
    Canonicalize function definition header lines.
    Example: `DefineFunction "<name>", <argc>, "<arg1>", ... {`
    """
    canonicalized_lines: list[str] = []

    for line in lines:
        if DEFINE_FUNCTION2_RE.match(strip_label(line)):
            line = neutralize_definefunction2_register_operands(line)

        if DEFINE_FUNCTION_ANY_RE.match(strip_label(line)):
            line = canonicalize_definefunction_header_line(line)

        canonicalized_lines.append(line)

    return canonicalized_lines

def canonicalize_labels(lines: list[str]) -> list[str]:
    """
    Canonicalize labels by renaming them by order of appearance.
    Example: `L0`, `L1`, `L2` etc.
    """
    label_map: dict[str, str] = {}
    label_next_idx = 0

    def map_label(label: str) -> str:
        nonlocal label_next_idx
        key = label.lower()
        if key not in label_map:
            label_map[key] = f"L{label_next_idx}"
            label_next_idx += 1
        return label_map[key]

    canonicalized_lines: list[str] = []

    for line in lines:
        line = LABEL_RE.sub(lambda m: map_label(m.group(0)), line)
        canonicalized_lines.append(line)

    return canonicalized_lines

def normalize_block(lines: list[str]) -> str:
    """
    Normalize a p-code block with multiple obscure techniques.
    """
    lines = [ln.rstrip() for ln in lines if ln.strip()] # remove blank lines
    lines = canonicalize_push_lines(lines)
    lines = canonicalize_number_literals(lines)
    lines = canonicalize_function_definition_headers(lines)
    lines = canonicalize_labels(lines)

    return "\n".join(lines) + "\n"

@dataclass(frozen=True)
class NormalizationStats:
    total_blocks: int
    named_blocks: int
    anonymous_blocks: int
    toplevel_blocks: int

def normalize_file(input_file: Path, output_dir: Path) -> NormalizationStats:
    """
    Split a p-code file into multiple normalized blocks and write them in the output directory.
    """
    text = input_file.read_text(encoding="utf-8", errors="replace")
    blocks = split_into_blocks(text)

    output_dir.mkdir(parents=True, exist_ok=True)

    named_count = anon_count = gap_count = 0

    for idx, (name, lines) in enumerate(blocks, start=1):
        block_file = output_dir / f"{idx:03d}_{name}.pcode"
        block_file.write_text(normalize_block(lines), encoding="utf-8")

        if name.startswith("__toplevel"):
            gap_count += 1
        elif name.startswith("__anonymous"):
            anon_count += 1
        else:
            named_count += 1

    return NormalizationStats(
        total_blocks = len(blocks),
        named_blocks = named_count,
        anonymous_blocks = anon_count,
        toplevel_blocks = gap_count,
    )
