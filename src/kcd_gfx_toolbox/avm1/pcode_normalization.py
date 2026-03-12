from pathlib import Path
from dataclasses import dataclass
import re
from .pcode_utils import REGISTER_REFERENCE_RE
from .pcode_parsing import (
    PcodeBlock,
    PcodeBlankLineWithLabel,
    PcodeInstruction,
    PcodeLine,
    PcodeOperand,
    PcodeStructural,
    is_pcode_instruction,
    parse_pcode_file,
)
from kcd_gfx_toolbox.utils import safe_filename


def find_function_name_and_start_line(
    lines: list[PcodeLine], define_function_idx: int, max_lookback: int = 64
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
        line = lines[i]

        if not is_pcode_instruction(line):
            continue

        # Found: Push <reg>, "Name"
        if (
            line.opcode == "Push"
            and len(line.operands) == 2
            and line.operands[0].type == "symbol"
            and REGISTER_REFERENCE_RE.fullmatch(str(line.operands[0].value))
            and line.operands[1].type == "string"
        ):
            return (i, line.operands[1].value)

        # Found: Push "Name" and there is at least one more line before.
        if line.opcode == "Push" and len(line.operands) == 1 and line.operands[0].type == "string" and i - 1 >= 0:
            prev = lines[i - 1]

            if not isinstance(prev, PcodeInstruction):
                continue

            if (
                prev.opcode == "Push"
                and len(prev.operands) == 1
                and prev.operands[0].type == "symbol"
                and REGISTER_REFERENCE_RE.fullmatch(str(prev.operands[0].value))
            ):
                return (i - 1, line.operands[0].value)

    return None


def find_function_end_line(lines: list[PcodeLine], define_function_idx: int) -> int:
    """
    Find the index of the line closing the function that starts at `define_function_idx`.
    Use brace-depth tracking to avoid stopping at nested function boundaries.
    Fall back to last line if no closing brace was found.
    """
    depth = 0
    opening_seen = False

    for i in range(define_function_idx, len(lines)):
        line = lines[i]

        if is_pcode_instruction(line) and line.opcode in ["DefineFunction", "DefineFunction2"]:
            opening_seen = True
            depth += 1
            continue

        if isinstance(line, PcodeStructural) and line.value == "}":
            depth -= 1

        # `opening_seen == True` means that we have entered the function body.
        # `depth <= 0` means we've closed it.
        if opening_seen and depth <= 0:
            return i

    return len(lines) - 1  # Fallback; should never happen with well-formed p-code.


def split_into_blocks(pcode_file: PcodeBlock) -> list[PcodeBlock]:
    """
    Splits a p-code text into a sequence of blocks:
    - Function blocks:
        - If the `DefineFunction`/`DefineFunction2` header has a non-empty name, that name is used and
          the block starts on the header line.
        - Otherwise, block name is inferred by scanning previous lines for member-binding patterns.
        - A trailing `SetMember` is included when present.
    - Top-level gap blocks between or around function blocks (for example, class property initialization).
    """
    blocks: list[PcodeBlock] = []
    name_occurrences: dict[str, int] = {}

    def add_block(name: str, a: int, b: int):
        blocks.append(PcodeBlock(lines=pcode_file.lines[a:b], name=name))

    i = 0
    next_gap_start = 0

    while i < len(pcode_file.lines):
        current = pcode_file.lines[i]

        # If we find a function definition instruction.
        if isinstance(current, PcodeInstruction) and current.opcode in ["DefineFunction", "DefineFunction2"]:
            assert current.operands[0] is not None
            assert current.operands[0].type == "string"
            declared_name = current.operands[0].value

            if declared_name:
                # The function definition header contains the function name.
                start, func_name = i, declared_name
            else:
                # No name is declared in the header, we need to look back at previous lines.
                func_info = find_function_name_and_start_line(pcode_file.lines, i)

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
            end = find_function_end_line(pcode_file.lines, i)

            # Include trailing SetMember if present on the next line.
            if (
                (end + 1) < len(pcode_file.lines)
                and isinstance(pcode_file.lines[end + 1], PcodeInstruction)
                and pcode_file.lines[end + 1].opcode == "SetMember"
            ):
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
    if next_gap_start < len(pcode_file.lines):
        add_block("__toplevel", next_gap_start, len(pcode_file.lines))

    return blocks


def canonicalize_push_lines(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize "Push" lines with multiple operands into single-operand "Push" lines.

    Example:
        Push register0, "GetWeight"
    =>
        Push register0

        Push "GetWeight"

    Preserve the label on the first line if present.
    """
    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        if is_pcode_instruction(line) and line.opcode == "Push" and len(line.operands) > 1:
            canonicalized_lines.append(line.replace(operands=[line.operands[0]]))

            for op in line.operands[1:]:
                canonicalized_lines.append(line.replace(operands=[op], label=None))

            continue

        canonicalized_lines.append(line)

    return canonicalized_lines


def canonicalize_numeric_literals(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize numbers to their simplest form.
    Examples:
        0.0 -> 0  |  1.0 -> 1  |  -0 -> 0  |  -8.0 -> -8
    """
    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        if not is_pcode_instruction(line) or not line.operands:
            canonicalized_lines.append(line)
            continue

        canonicalized_operands: list[PcodeOperand] = []

        for operand in line.operands:
            if operand.type != "numeric":
                canonicalized_operands.append(operand)
                continue

            value = str(operand.value)

            if re.fullmatch(r"-?\d+\.0", value):
                value = value[:-2]
            elif value == "-0":
                value = "0"

            canonicalized_operands.append(PcodeOperand(type=operand.type, value=value))

        canonicalized_lines.append(line.replace(operands=canonicalized_operands))

    return canonicalized_lines


def canonicalize_function_definition_headers(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize function definition header lines.
    Example:
        `DefineFunction2 "<name>", 2, 12, ..., 2, "<arg1>", 3, "<arg2>" {`
    =>
        `DefineFunction "<name>", 2, "<arg1>", "<arg2>" {`
    """
    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        if not is_pcode_instruction(line) or not line.is_function_definition():
            canonicalized_lines.append(line)
            continue

        new_operands = line.operands[:2] + [op for op in line.operands[2:] if op.type == "string"]
        canonicalized_lines.append(line.replace(opcode="DefineFunction", operands=new_operands))

    return canonicalized_lines


def canonicalize_register_references_in_function_block(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize register references (`registerN` and `StoreRegister N`) by reindexing them
    by "first write" order per function scope.

    Register indices first seen in `StoreRegister` instructions get canonical indices first.
    Registers only ever read are assigned afterwards, in order of appearance.

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
        Push register2, "m_Count"
        GetMember
        Push register1
        GetMember
        Push 0.0
        StoreRegister 1
        Pop
        Push register3, register2
    """
    # Find the function definition header line.
    define_function_index = next(
        (i for i, line in enumerate(lines) if is_pcode_instruction(line) and line.is_function_definition()),
        None,
    )

    # If this block is not a function block, we skip this process.
    if define_function_index is None:
        return lines

    canonicalized_lines: list[PcodeLine] = lines.copy()

    class RegisterScope:
        def __init__(self):
            self.registers_seen: dict[str, int] = {}
            self.next_reg_index = 1

        def canonicalize_register_index(self, reg_idx: str) -> int:
            if reg_idx not in self.registers_seen:
                self.registers_seen[reg_idx] = self.next_reg_index
                self.next_reg_index += 1
            return self.registers_seen[reg_idx]

    def _canonicalize_line(line: PcodeLine, scope: RegisterScope) -> PcodeLine:
        if not is_pcode_instruction(line):
            return line

        if line.opcode == "StoreRegister":
            canon_index = scope.canonicalize_register_index(str(line.operands[0].value))
            return line.replace(operands=[PcodeOperand(type="numeric", value=str(canon_index))] + line.operands[1:])

        canonicalized_operands: list[PcodeOperand] = []

        for operand in line.operands:
            if operand.type != "symbol" or not REGISTER_REFERENCE_RE.fullmatch(str(operand.value)):
                canonicalized_operands.append(operand)
                continue

            reg_match = REGISTER_REFERENCE_RE.match(str(operand.value))
            assert reg_match is not None
            canon_index = scope.canonicalize_register_index(reg_match.group("regindex"))
            canonicalized_operands.append(PcodeOperand(type="symbol", value=f"register{canon_index}"))

        return line.replace(operands=canonicalized_operands)

    def _canonicalize_function_scope(define_idx: int) -> int:
        """Canonicalize all lines in a function scope and call itself recursively when encountering a nested function"""
        end_idx = find_function_end_line(canonicalized_lines, define_idx)
        scope = RegisterScope()

        # First pass: scan `StoreRegister N` instructions and pre-assign canonical indices
        # to stabilize register assignment independently from read-order churn.
        i = define_idx + 1

        while i <= end_idx:
            current = canonicalized_lines[i]

            if not is_pcode_instruction(current):
                i += 1
                continue

            # Skip nested function bodies. They will be canonicalized recursively later.
            if current.is_function_definition():
                nested_end_idx = find_function_end_line(canonicalized_lines, i)
                i = nested_end_idx + 1
                continue

            if current.opcode == "StoreRegister":
                scope.canonicalize_register_index(str(current.operands[0].value))

            i += 1

        # Second pass: rewrite register references using the pre-assigned map,
        # and assign indices to read-only registers on first encounter.
        i = define_idx + 1

        while i <= end_idx:
            current = canonicalized_lines[i]

            if not is_pcode_instruction(current):
                i += 1
                continue

            if current.is_function_definition():
                nested_end_idx = _canonicalize_function_scope(i)
                i = nested_end_idx + 1
                continue

            canonicalized_lines[i] = _canonicalize_line(canonicalized_lines[i], scope)
            i += 1

        return end_idx

    _canonicalize_function_scope(define_function_index)

    return canonicalized_lines


def normalize_not_not_if_patterns(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Normalize another decompilation oddity. `Not Not If ...` can be simplified to just `If ...`.
    """
    canonicalized_lines: list[PcodeLine] = []
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
            (not is_pcode_instruction(current_line) or current_line.opcode != "Not")
            and is_pcode_instruction(next1_line)
            and next1_line.opcode == "Not"
            and next1_line.label is None
            and is_pcode_instruction(next2_line)
            and next2_line.opcode == "Not"
            and next2_line.label is None
            and is_pcode_instruction(next3_line)
            and next3_line.opcode == "If"
        ):
            canonicalized_lines.append(current_line)
            canonicalized_lines.append(next3_line)
            i += 4
            continue

        canonicalized_lines.append(current_line)
        i += 1  # Nothing special, go on next line.

    return canonicalized_lines


def list_label_references(lines: list[PcodeLine]) -> set[str]:
    """
    Return a set of all label references (not definitions/prefixes) found in lines.
    """
    referenced_labels: set[str] = set()

    for line in lines:
        if is_pcode_instruction(line) and line.opcode in ["If", "Jump"] and line.operands:
            referenced_labels.add(str(line.operands[0].value).lower())

    return referenced_labels


def strip_unreferenced_label_definitions(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Remove label prefixes (definitions) when the label is never referenced within the same block.
    """
    referenced_labels = list_label_references(lines)
    cleaned_lines: list[PcodeLine] = []

    for line in lines:
        if line.label is None or line.label.lower() in referenced_labels:
            cleaned_lines.append(line)
            continue

        if isinstance(line, PcodeBlankLineWithLabel):
            continue  # Drop what would become "just a blank line".

        cleaned_lines.append(line.replace(label=None))

    return cleaned_lines


def canonicalize_labels(lines: list[PcodeLine]) -> list[PcodeLine]:
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

    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        canon_line = line.replace()

        if line.label is not None:
            # If the line has a label prefix.
            canon_line = canon_line.replace(label=map_label(line.label))

        if is_pcode_instruction(line) and line.opcode in ["If", "Jump"] and line.operands:
            # If we match exactly `If <label>` or `Jump <label>`.
            new_target = map_label(str(line.operands[0].value))
            canon_line = canon_line.replace(
                operands=[PcodeOperand(type="symbol", value=str(new_target))] + line.operands[1:]
            )

        canonicalized_lines.append(canon_line)

    return canonicalized_lines


def normalize_block(block: PcodeBlock) -> PcodeBlock:
    """
    Normalize a p-code block with multiple obscure techniques.
    """
    lines = block.lines
    lines = canonicalize_push_lines(lines)
    lines = canonicalize_numeric_literals(lines)
    lines = canonicalize_function_definition_headers(lines)
    lines = canonicalize_register_references_in_function_block(lines)
    lines = strip_unreferenced_label_definitions(lines)
    lines = canonicalize_labels(lines)
    lines = normalize_not_not_if_patterns(lines)

    return PcodeBlock(lines=lines, name=block.name)


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
    pcode_file = parse_pcode_file(input_file)
    blocks = split_into_blocks(pcode_file)

    output_dir.mkdir(parents=True, exist_ok=True)

    named_count = anon_count = gap_count = 0

    for idx, block in enumerate(blocks, start=1):
        assert block.name is not None
        block_file = output_dir / f"{idx:03d}_{block.name}.pcode"
        block_file.write_text(normalize_block(block).render() + "\n", encoding="utf-8")

        if block.name.startswith("__toplevel"):
            gap_count += 1
        elif block.name.startswith("__anonymous"):
            anon_count += 1
        else:
            named_count += 1

    return NormalizationStats(
        total_blocks=len(blocks),
        named_blocks=named_count,
        anonymous_blocks=anon_count,
        toplevel_blocks=gap_count,
    )
