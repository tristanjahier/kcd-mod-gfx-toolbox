from pathlib import Path
import re
from dataclasses import dataclass
from .util import safe_filename

WORD_TOKEN = r"[a-zA-Z_][a-zA-Z\d_]*"
LABEL_PREFIXED_LINE_RE = re.compile(rf"^\s*(?P<prefix>(?P<label>{WORD_TOKEN})\s*:)\s*(?P<rest>.*)$")
LABEL_REFERENCED_LINE_RE = re.compile(rf"^(?P<opcode>If|Jump)\s+(?P<label>{WORD_TOKEN})$", flags=re.IGNORECASE)

DOT0_RE = re.compile(r"\b(-?\d+)\.0\b")  # 0.0, 1.0, 5.0...
NEG0_RE = re.compile(r"(^|[\s,])-0(?=($|[\s,]))")

PUSH_SINGLE_RE = re.compile(r'^\s*Push\s+(?:register\d+|r\d+)\s*,\s*"([^"]+)"\s*$')
PUSH_OBJ_RE = re.compile(r"^\s*Push\s+(?:register\d+|r\d+)\s*$")
PUSH_NAME_RE = re.compile(r'^\s*Push\s+"([^"]+)"\s*$')

DEFINE_FUNCTION_ANY_RE = re.compile(r"^\s*DefineFunction(?:2)?\b")
DEFINE_FUNCTION_HEADER_RE = re.compile(r'^\s*DefineFunction(?:2)?\s*"([^"]*)"\s*,\s*(\d+)')


def strip_label(line: str) -> str:
    """
    Remove the leading label if present (like `loc044b:` or `L12:`).
    """
    match = LABEL_PREFIXED_LINE_RE.match(line)
    return match.group("rest") if match else line


def find_function_name_and_start_line(
    lines: list[str], define_function_idx: int, max_lookback: int = 64
) -> tuple[int, str] | None:
    """
    For a function definition keyword found at line `define_function_idx`,
    look back for a member-binding pattern, which can be either:
        a. Push <reg>, "Name"
        b. Push <reg>
           Push "Name"

    Return the start index and the function name if found, else None.
    """
    i0 = max(0, define_function_idx - max_lookback)  # lower bound of the lookback window

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

    return len(lines) - 1  # Fallback; should never happen with well-formed p-code.


def split_into_blocks(pcode_text: str) -> list[tuple[str, list[str]]]:
    """
    Splits a p-code text into a sequence of blocks:
    - Function blocks:
        - If the `DefineFunction`/`DefineFunction2` header has a non-empty name, that name is used and
          the block starts on the header line.
        - Otherwise, block name is inferred by scanning previous lines for member-binding patterns.
        - A trailing `SetMember` is included when present.
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
            header_match = DEFINE_FUNCTION_HEADER_RE.match(current)
            declared_name = header_match.group(1) if header_match else None

            if declared_name:
                # The function definition header contains the function name.
                start, func_name = i, declared_name
            else:
                # No name is declared in the header, we need to look back at previous lines.
                func_info = find_function_name_and_start_line(lines, i)

                # Keep the name found from lookback only if we can include those lookback lines in this block.
                # Otherwise, avoid carrying a stale name from already-consumed lines. Prevent overlapping.
                if func_info is not None and func_info[0] >= next_gap_start:
                    start, func_name = func_info
                else:
                    start, func_name = i, "__anonymous"

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
                block_name = f"{block_name}__{count + 1}"

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


def tokenize_line(line: str) -> list[tuple[int, str]]:
    """
    Split a line in a sequence of tokens.

    Backslash escaping is honored while scanning quoted text.
    Whitespace is ignored.

    Example:
        `label56:Push register1, "cagada, ahah", 0.0, 6 {`
    =>
        label56 | : | Push | register1 | , | "cagada, ahah" | 0.0 | 6 | {
    """
    tokens: list[tuple[int, str]] = []
    separators = [":", ",", "{", "}"]
    buffer = []  # characters encountered before a token separator
    buffer_start = 0
    quoting = False
    escaping = False

    for pos, char in enumerate(line):
        if escaping:
            buffer.append(char)
            escaping = False
            continue
        if char == "\\" and quoting:
            buffer.append(char)
            escaping = True
            continue
        if char == '"':
            buffer.append(char)
            quoting = not quoting
            continue
        if (char.isspace() or char in separators) and not quoting:
            # We are not inside a string, and we met a token separator (or a whitespace).
            token = "".join(buffer)
            if token:
                tokens.append((buffer_start, token))

            if char in separators:
                tokens.append((pos, char))

            buffer = []  # we just met a separator, so we reset the buffer
            buffer_start = pos + 1
            continue

        buffer.append(char)

    if token := "".join(buffer):
        tokens.append((buffer_start, token))

    return tokens


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
    return [tok for _, tok in tokenize_line(s) if tok != ","]


def extract_label_from_line(line: str) -> tuple[str, str | None]:
    """
    Extract the label of a p-code line if any. Return the rest of the line and the label.
    """
    if match := LABEL_PREFIXED_LINE_RE.match(line):
        return (match.group("rest"), match.group("label"))

    return (line, None)


def line_has_label(line: str) -> bool:
    """
    Determine if a line has a label.
    """
    return LABEL_PREFIXED_LINE_RE.match(line) is not None


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
            operands = split_comma_separated_operands(labelless_line[len("Push ") :])
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
        line = NEG0_RE.sub(r"\g<1>0", line)

        canonicalized_lines.append(line)

    return canonicalized_lines


def canonicalize_function_definition_headers(lines: list[str]) -> list[str]:
    """
    Canonicalize function definition header lines.
    Example:
        `DefineFunction2 "<name>", 2, 12, ..., 2, "<arg1>", 3, "<arg2>" {`
    =>
        `DefineFunction "<name>", 2, "<arg1>", "<arg2>" {`
    """
    canonicalized_lines: list[str] = []

    for line in lines:
        # Put aside the label if present.
        labelless_line, label = extract_label_from_line(line)

        if not DEFINE_FUNCTION_ANY_RE.match(labelless_line) or not (
            match := DEFINE_FUNCTION_HEADER_RE.match(labelless_line)
        ):
            canonicalized_lines.append(line)
            continue

        func_name = match.group(1)
        argc = int(match.group(2))
        quoted_operands = re.findall(r'"([^"]*)"', labelless_line)
        arg_names = quoted_operands[1 : 1 + argc]

        normalized_line = f'DefineFunction "{func_name}", {argc}'
        for arg in arg_names:
            normalized_line += f', "{arg}"'
        normalized_line += " {"

        # Put back the label if it was present.
        label_prefix = label + ":" if label else ""

        canonicalized_lines.append(f"{label_prefix}{normalized_line}")

    return canonicalized_lines


def canonicalize_register_references_in_function_block(lines: list[str]) -> list[str]:
    """
    Canonicalize register references (`registerN` and `StoreRegister N`) by reindexing them
    by order of appearance.

    Example:
        Push register2, "m_Count"
        GetMember
        Push register8
        GetMember
        Push 0.0
        StoreRegister 8
        Pop
        Push register3, register2
    =>
        Push register1, "m_Count"
        GetMember
        Push register2
        GetMember
        Push 0.0
        StoreRegister 2
        Pop
        Push register3, register1
    """
    # Find the function definition header line.
    define_function_index = next(
        (i for i, line in enumerate(lines) if DEFINE_FUNCTION_ANY_RE.match(strip_label(line).strip())),
        None,
    )

    # If this block is not a function block, we skip this process.
    if define_function_index is None:
        return lines

    canonicalized_lines: list[str] = lines.copy()
    read_register_re = re.compile(r"^register(\d+)$")
    store_register_operand_re = re.compile(r"^\d+$")

    class RegisterScope:
        def __init__(self):
            self.registers_seen: dict[str, int] = {}
            self.next_reg_index = 1

        def canonicalize_register_index(self, reg_idx: str) -> int:
            if reg_idx not in self.registers_seen:
                self.registers_seen[reg_idx] = self.next_reg_index
                self.next_reg_index += 1
            return self.registers_seen[reg_idx]

    def canonicalize_line(line: str, scope: RegisterScope) -> str:
        replacements: list[tuple[tuple[int, str], str]] = []
        tokens = tokenize_line(line)
        j = 0

        while j < len(tokens):
            pos, tok = tokens[j]

            if tok == "StoreRegister" and j + 1 < len(tokens):
                next_pos, next_tok = tokens[j + 1]
                if store_register_operand_re.fullmatch(next_tok):
                    canon_index = scope.canonicalize_register_index(next_tok)
                    replacements.append(((next_pos, next_tok), str(canon_index)))
                    j += 2
                    continue

            if match := read_register_re.fullmatch(tok):
                canon_index = scope.canonicalize_register_index(match.group(1))
                replacements.append(((pos, tok), f"register{canon_index}"))

            j += 1

        for (pos, original), replacement in reversed(replacements):
            line = line[:pos] + replacement + line[pos + len(original) :]

        return line

    def canonicalize_function_scope(define_idx: int) -> int:
        """Canonicalize all lines in a function scope and call itself recursively when encountering a nested function"""
        end_idx = find_function_end_line(canonicalized_lines, define_idx)
        scope = RegisterScope()

        i = define_idx + 1
        while i <= end_idx:
            current = strip_label(canonicalized_lines[i]).strip()

            if DEFINE_FUNCTION_ANY_RE.match(current):
                nested_end_idx = canonicalize_function_scope(i)
                i = nested_end_idx + 1
                continue

            canonicalized_lines[i] = canonicalize_line(canonicalized_lines[i], scope)
            i += 1

        return end_idx

    canonicalize_function_scope(define_function_index)

    return canonicalized_lines


def normalize_not_not_if_patterns(lines: list[str]) -> list[str]:
    """
    Normalize another decompilation oddity. `Not Not If ...` can be simplified to just `If ...`.
    """
    canonicalized_lines: list[str] = []
    i = 0

    while i < len(lines):
        current_line = lines[i]
        next1_line = lines[i + 1] if i + 1 < len(lines) else None
        next2_line = lines[i + 2] if i + 2 < len(lines) else None
        next3_line = lines[i + 3] if i + 3 < len(lines) else None

        # With the following condition we want to match this kind of sequence:
        #   Equals2
        #   Not
        #   Not
        #   If loc3588
        # and simplify in:
        #   Equals2
        #   If loc3588
        # `Not` lines cannot have labels for this to apply!
        if (
            strip_label(current_line).strip() != "Not"
            and next1_line is not None
            and not line_has_label(next1_line)
            and next1_line.strip() == "Not"
            and next2_line is not None
            and not line_has_label(next2_line)
            and next2_line.strip() == "Not"
            and next3_line is not None
            and strip_label(next3_line).strip().startswith("If ")
        ):
            canonicalized_lines.append(current_line)
            canonicalized_lines.append(next3_line)
            i += 4
            continue

        canonicalized_lines.append(current_line)
        i += 1  # Nothing special, go on next line.

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

    word_token_re = re.compile(WORD_TOKEN)

    canonicalized_lines: list[str] = []

    for line in lines:
        # First, we read the line to find labels.
        labelless_line, label_prefix = extract_label_from_line(line)

        if label_prefix is not None:
            # If the line has a label prefix.
            map_label(label_prefix)

        if match := LABEL_REFERENCED_LINE_RE.match(labelless_line.strip()):
            # If we match exactly `If <label>` or `Jump <label>`.
            map_label(match.group("label"))

        # After label discovery and remapping: modify the line.
        # Working on tokens allows replacing only what is needed, without touching the whitespaces.
        # Important: proceed from the end of the line toward the start.
        # This prevents position shifting when performing multiple substitutions per line.
        word_tokens = [tok for tok in tokenize_line(line) if word_token_re.fullmatch(tok[1])]
        word_tokens.sort(key=lambda t: t[0], reverse=True)

        for pos, tok in word_tokens:
            if tok.lower() in label_map:
                line = line[:pos] + map_label(tok) + line[pos + len(tok) :]

        canonicalized_lines.append(line)

    return canonicalized_lines


def normalize_block(lines: list[str]) -> str:
    """
    Normalize a p-code block with multiple obscure techniques.
    """
    lines = [ln.rstrip() for ln in lines if ln.strip()]  # remove blank lines
    lines = canonicalize_push_lines(lines)
    lines = canonicalize_number_literals(lines)
    lines = canonicalize_function_definition_headers(lines)
    lines = canonicalize_register_references_in_function_block(lines)
    lines = canonicalize_labels(lines)
    lines = normalize_not_not_if_patterns(lines)

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
        total_blocks=len(blocks),
        named_blocks=named_count,
        anonymous_blocks=anon_count,
        toplevel_blocks=gap_count,
    )
