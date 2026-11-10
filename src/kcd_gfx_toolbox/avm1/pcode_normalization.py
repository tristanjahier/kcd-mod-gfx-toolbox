import json
import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from kcd_gfx_toolbox.utils import safe_filename

from .pcode_parsing import (
    PcodeBlankLineWithLabel,
    PcodeBlock,
    PcodeInstruction,
    PcodeLine,
    PcodeOperand,
    PcodeStructural,
    is_pcode_instruction,
    merge_pcode_lines_sources,
    parse_pcode_file,
)
from .pcode_utils import REGISTER_REFERENCE_RE


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

            if (
                is_pcode_instruction(prev)
                and prev.opcode == "Push"
                and len(prev.operands) == 1
                and prev.operands[0].type == "symbol"
                and REGISTER_REFERENCE_RE.fullmatch(str(prev.operands[0].value))
            ):
                return (i - 1, line.operands[0].value)

    return None


def find_scope_end_line(lines: list[PcodeLine], scope_start_idx: int) -> int:
    """
    Find the index of the line closing the scope that starts at `scope_start_idx`.

    Use brace-depth tracking to avoid stopping at nested scope boundaries.
    Fall back to last line if no closing brace was found.
    """
    depth = 0
    opening_seen = False

    for i in range(scope_start_idx, len(lines)):
        line = lines[i]

        if is_pcode_instruction(line) and line.has_opening_brace():
            opening_seen = True
            depth += 1
            continue

        if isinstance(line, PcodeStructural) and line.value == "}":
            depth -= 1

        # `opening_seen == True` means that we have entered a scope.
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
        occurrences = name_occurrences.get(name.lower(), 0)
        name_occurrences[name.lower()] = occurrences + 1
        if occurrences > 0:
            name = f"{name}_{occurrences + 1}"
        blocks.append(PcodeBlock(lines=pcode_file.lines[a:b], name=name))

    i = 0
    next_gap_start = 0

    while i < len(pcode_file.lines):
        current = pcode_file.lines[i]

        # If we find a function definition instruction.
        if is_pcode_instruction(current) and current.opcode in ["DefineFunction", "DefineFunction2"]:
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
            end = find_scope_end_line(pcode_file.lines, i)

            # Include trailing SetMember if present on the next line.
            if (
                (end + 1) < len(pcode_file.lines)
                and is_pcode_instruction(pcode_file.lines[end + 1])
                and pcode_file.lines[end + 1].opcode == "SetMember"
            ):
                end += 1

            block_name = safe_filename(func_name)

            if not block_name:
                block_name = "__anonymous"

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
        changed = False

        for operand in line.operands:
            if operand.type != "numeric":
                canonicalized_operands.append(operand)
                continue

            value = str(operand.value)

            if re.fullmatch(r"-?\d+\.0", value):
                value = value[:-2]

            if value == "-0":
                value = "0"

            if value != operand.value:
                canonicalized_operands.append(operand.replace(value=value))
                changed = True
            else:
                canonicalized_operands.append(operand)

        canonicalized_lines.append(line.replace(operands=canonicalized_operands) if changed else line)

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

    def _canonicalize_line(line: PcodeInstruction, scope: RegisterScope) -> PcodeLine:
        if line.opcode == "StoreRegister":
            old_index = str(line.operands[0].value)
            canon_index = str(scope.canonicalize_register_index(old_index))
            if canon_index != old_index:
                return line.replace(operands=[line.operands[0].replace(value=canon_index)] + line.operands[1:])
            else:
                return line

        if not line.operands:
            return line

        canonicalized_operands: list[PcodeOperand] = []
        changed = False

        for operand in line.operands:
            if operand.type != "symbol" or (reg_match := REGISTER_REFERENCE_RE.fullmatch(str(operand.value))) is None:
                canonicalized_operands.append(operand)
                continue

            old_index = reg_match.group("regindex")
            canon_index = str(scope.canonicalize_register_index(old_index))

            if canon_index != old_index:
                canonicalized_operands.append(operand.replace(value=f"register{canon_index}"))
                changed = True
            else:
                canonicalized_operands.append(operand)

        if not changed:
            return line

        return line.replace(operands=canonicalized_operands)

    def _canonicalize_function_scope(define_idx: int) -> int:
        """Canonicalize all lines in a function scope and call itself recursively when encountering a nested function"""
        end_idx = find_scope_end_line(canonicalized_lines, define_idx)
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
                nested_end_idx = find_scope_end_line(canonicalized_lines, i)
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

            canonicalized_lines[i] = _canonicalize_line(current, scope)
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
        changes: dict[str, Any] = {}

        if line.label is not None:
            # If the line has a label prefix.
            new_label = map_label(line.label)
            if new_label != line.label:
                changes["label"] = new_label

        if is_pcode_instruction(line) and line.opcode in ["If", "Jump"] and line.operands:
            # If we match exactly `If <label>` or `Jump <label>`.
            old_target = str(line.operands[0].value)
            new_target = map_label(old_target)
            if new_target != old_target:
                changes["operands"] = [line.operands[0].replace(value=new_target)] + line.operands[1:]

        if changes:
            canonicalized_lines.append(line.replace(**changes))
        else:
            canonicalized_lines.append(line)

    return canonicalized_lines


def canonicalize_increment_decrement_patterns(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize 3 different increment or decrement patterns.
    - `Push registerN / Push 1 / Add2|Subtract / StoreRegister N`
    - `Push "name" / GetMember / Push 1 / Add2|Subtract / SetMember`
    - `Push "name" / GetVariable / Push 1 / Add2|Subtract / SetVariable`
    - In each of the above patterns, `Return` can substitute the last instruction.
    """

    def _line_is_push_register(line: PcodeLine) -> bool:
        return bool(
            is_pcode_instruction(line)
            and line.opcode == "Push"
            and len(line.operands) == 1
            and line.operands[0].type == "symbol"
            and REGISTER_REFERENCE_RE.fullmatch(str(line.operands[0].value))
        )

    def _line_is_push_1(line: PcodeLine) -> bool:
        return bool(
            is_pcode_instruction(line)
            and line.opcode == "Push"
            and len(line.operands) == 1
            and line.operands[0].type == "numeric"
            and line.operands[0].value == "1"
        )

    def _line_is_add(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode in ["Add", "Add2"])

    def _line_is_subtract(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "Subtract")

    def _line_is_store_register(line: PcodeLine) -> bool:
        return bool(
            is_pcode_instruction(line)
            and line.opcode == "StoreRegister"
            and len(line.operands) == 1
            and line.operands[0].type == "numeric"
        )

    def _line_is_get_member(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "GetMember" and not line.operands)

    def _line_is_set_member(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "SetMember" and not line.operands)

    def _line_is_push_string(line: PcodeLine) -> bool:
        return bool(
            is_pcode_instruction(line)
            and line.opcode == "Push"
            and len(line.operands) == 1
            and line.operands[0].type == "string"
        )

    def _line_is_get_variable(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "GetVariable" and not line.operands)

    def _line_is_set_variable(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "SetVariable" and not line.operands)

    def _line_is_return(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "Return" and not line.operands)

    canonicalized_lines: list[PcodeLine] = []

    i = 0

    while i < len(lines):
        if (i + 4) > len(lines):
            canonicalized_lines.append(lines[i])
            i += 1
            continue

        hunk = lines[i : i + 4]  # current plus next 3 lines

        # Pattern 1: Push registerN / Push 1 / Add2|Subtract / StoreRegister N
        if (
            _line_is_push_register(hunk[0])
            and _line_is_push_1(hunk[1])
            and (_line_is_add(hunk[2]) or _line_is_subtract(hunk[2]))
            and (_line_is_store_register(hunk[3]) or _line_is_return(hunk[3]))
            and hunk[1].label is None
            and hunk[2].label is None
        ):
            register_1 = REGISTER_REFERENCE_RE.match(hunk[0].operands[0].value).group("regindex")
            register_2 = hunk[3].operands[0].value if _line_is_store_register(hunk[3]) else None

            if _line_is_return(hunk[3]) or register_1 == register_2:
                opcode = "Increment" if hunk[2].opcode in ["Add", "Add2"] else "Decrement"
                crement_pcode = PcodeInstruction(
                    source_lines=merge_pcode_lines_sources(hunk[1], hunk[2]), opcode=opcode, operands=[]
                )
                canonicalized_lines.extend([hunk[0], crement_pcode, hunk[3]])
                i += 4
                continue

        # Pattern 2: Push "name" / GetMember / Push 1 / Add2|Subtract / SetMember
        # Pattern 3: Push "name" / GetVariable / Push 1 / Add2|Subtract / SetVariable
        elif (
            # Read previous line from canonicalized lines because it has already been processed.
            len(canonicalized_lines) > 0
            and _line_is_push_string(canonicalized_lines[-1])
            and (
                # Pair of (GetMember, SetMember|Return) OR pair of (GetVariable, SetVariable|Return).
                _line_is_get_member(hunk[0])
                and (_line_is_set_member(hunk[3]) or _line_is_return(hunk[3]))
                or _line_is_get_variable(hunk[0])
                and (_line_is_set_variable(hunk[3]) or _line_is_return(hunk[3]))
            )
            and _line_is_push_1(hunk[1])
            and (_line_is_add(hunk[2]) or _line_is_subtract(hunk[2]))
            and hunk[1].label is None
            and hunk[2].label is None
        ):
            opcode = "Increment" if hunk[2].opcode in ["Add", "Add2"] else "Decrement"
            crement_pcode = PcodeInstruction(
                source_lines=merge_pcode_lines_sources(hunk[1], hunk[2]), opcode=opcode, operands=[]
            )
            canonicalized_lines.extend([hunk[0], crement_pcode, hunk[3]])
            i += 4
            continue

        canonicalized_lines.append(lines[i])
        i += 1

    return canonicalized_lines


def canonicalize_constant_pool(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Strip all operands from ConstantPool instructions.
    It is safe to do because ffdec copies constant names wherever they are used when exporting p-code text.
    Therefore in practice it never occurs that a change in the constant pool is the only change.
    """
    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        if not is_pcode_instruction(line) or line.opcode != "ConstantPool":
            canonicalized_lines.append(line)
            continue

        canonicalized_lines.append(line.replace(operands=[PcodeOperand(type="string", value="")]))

    return canonicalized_lines


def canonicalize_string_concatenation(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Canonicalize string concatenation patterns.
    Example:
        Push "FSCommand:"
        Push "OnFastTravelPath"
        StringAdd
    """

    def _line_is_push_string(line: PcodeLine) -> bool:
        return bool(
            is_pcode_instruction(line)
            and line.opcode == "Push"
            and len(line.operands) == 1
            and line.operands[0].type == "string"
        )

    def _line_is_stringadd(line: PcodeLine) -> bool:
        return bool(is_pcode_instruction(line) and line.opcode == "StringAdd" and not line.operands)

    canonicalized_lines: list[PcodeLine] = []

    i = 0

    while i < len(lines):
        if (i + 3) > len(lines):
            canonicalized_lines.append(lines[i])
            i += 1
            continue

        hunk = lines[i : i + 3]  # current plus next 2 lines

        if (
            not _line_is_push_string(hunk[0])
            or not _line_is_push_string(hunk[1])
            or not _line_is_stringadd(hunk[2])
            or hunk[1].label is not None
            or hunk[2].label is not None
        ):
            canonicalized_lines.append(lines[i])
            i += 1
            continue

        concat_push = PcodeInstruction(
            source_lines=merge_pcode_lines_sources(*hunk),
            opcode="Push",
            operands=[PcodeOperand(type="string", value=hunk[0].operands[0].value + hunk[1].operands[0].value)],
            label=hunk[0].label,
        )

        canonicalized_lines.append(concat_push)
        i += 3

    return canonicalized_lines


def canonicalize_geturl2(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Set every GetURL2 3rd operand to 0.
    Example: `GetURL2 false, false, 1` -> `GetURL2 false, false, 0`.

    In KCD these patterns are often bound to FSCommand calls.
    The current code is probably too naive.
    """
    canonicalized_lines: list[PcodeLine] = []

    for line in lines:
        # TODO: Verify that GetURL2 is always bound to a FSCommand call.
        if (
            is_pcode_instruction(line)
            and line.opcode == "GetURL2"
            and len(line.operands) == 3
            and line.operands[0].type == "boolean"
            and line.operands[1].type == "boolean"
            and line.operands[2].type == "numeric"
            and line.operands[2].value != "0"
        ):
            new_operands = line.operands[:2] + [line.operands[2].replace(value="0")]
            canonicalized_lines.append(line.replace(operands=new_operands))
        else:
            canonicalized_lines.append(line)

    return canonicalized_lines


def find_outer_function_boundaries(lines: list[PcodeLine]) -> tuple[int, int] | None:
    """
    Return `(header index, closing brace index)` of the block's outer function, or None if not found.
    """
    header_idx = next(
        (i for i, line in enumerate(lines) if is_pcode_instruction(line) and line.is_function_definition()),
        None,
    )

    if header_idx is None:
        # Some blocks do not contain a function (e.g. top-level).
        return None

    return (header_idx, find_scope_end_line(lines, header_idx))


def is_branch_target(line: PcodeLine, referenced_labels: set[str]) -> bool:
    """
    Determine whether a jump can land on the line, i.e. whether its label is referenced.

    Unreferenced labels are ignored, as `strip_unreferenced_label_definitions` would remove them anyway.
    """
    return line.label is not None and line.label.lower() in referenced_labels


def is_undefined_register_initializer(lines: list[PcodeLine], i: int, referenced_labels: set[str]) -> bool:
    """
    Determine whether lines `i`, `i+1` and `i+2` form a `Push undefined` / `StoreRegister N` / `Pop` triple
    where no line is a branch target.
    """
    push, store, pop = lines[i], lines[i + 1], lines[i + 2]

    return bool(
        is_pcode_instruction(push)
        and push.opcode == "Push"
        and len(push.operands) == 1
        and push.operands[0].type == "symbol"
        and push.operands[0].value == "undefined"
        and not is_branch_target(push, referenced_labels)
        and is_pcode_instruction(store)
        and store.opcode == "StoreRegister"
        and len(store.operands) == 1
        and store.operands[0].type == "numeric"
        and not is_branch_target(store, referenced_labels)
        and is_pcode_instruction(pop)
        and pop.opcode == "Pop"
        and not pop.operands
        and not is_branch_target(pop, referenced_labels)
    )


OPAQUE_CONTROL_FLOW_OPCODES = {
    "Throw",
    "Try",
    "Catch",
    "WaitForFrame",
    "WaitForFrame2",
}
"""
Opcodes that move control somewhere this analysis does not model, and therefore could reach anything.

`Throw` lands on a handler, which is not modeled here. Note that it is deliberately not treated
as an exit, because a handler in the same function would still be able to read a register.
`Try` and `Catch` open exception-handling blocks: any instruction of a `Try` block can transfer
control to its `Catch` block, and that is not modeled either.
`WaitForFrame` and `WaitForFrame2` skip a number of *actions* rather than branching to a label,
so their destination cannot be recovered from the operands the way `If` and `Jump` targets can.
"""


def find_prologue_undefined_initializers(lines: list[PcodeLine], start_idx: int, end_idx: int) -> list[int]:
    """
    Return the indices of every undefined-initializer triple in the function's straight-line prologue:
    from the header up to the first referenced label definition, branch, or opaque control flow opcode.

    Nested function definitions are stepped over as a whole, header line included. They are
    self-contained, so neither their branches nor their own opening triples belong to the enclosing
    prologue, and a label on a nested header does not end it either. That is harmless: the prologue
    only selects candidates, and the read analysis decides whether each one can be dropped.
    """
    referenced_labels = list_label_references(lines)
    triples: list[int] = []
    i = start_idx + 1

    while i <= end_idx and i < len(lines):
        line = lines[i]

        # Step over nested functions.
        if is_pcode_instruction(line) and line.is_function_definition():
            i = find_scope_end_line(lines, i) + 1
            continue

        if is_branch_target(line, referenced_labels):
            # A branch can land here, so we are no longer in "straight-line code".
            break

        if is_pcode_instruction(line) and (line.opcode in ["If", "Jump"] or line.opcode in OPAQUE_CONTROL_FLOW_OPCODES):
            break

        if i + 2 > end_idx or i + 2 >= len(lines):
            # We reached the end and there are not enough lines for a triple.
            break

        if is_undefined_register_initializer(lines, i, referenced_labels):
            triples.append(i)
            i += 3
            continue

        i += 1

    return triples


class BranchResolution(Enum):
    """
    What a branch instruction resolves to when its target is not a line within the function scope.
    """

    LEAVES_FUNCTION = auto()
    """
    The target is not defined anywhere in the block.

    In practice, it is always the instruction right after the block, which is the usual way of compiling
    a bare `return;` in the middle of the function.
    Running past the end of the function body is how control normally exits without returning a value in AVM1.

    The function execution ends, so nothing beyond the branch can read the register, assuming registers are
    private to the call.
    """

    UNRESOLVED = auto()
    """
    The destination is unknowable, so the branch is treated as potentially reaching everything.

    Either the operand is not a label, or the target is defined in the block but outside the
    scope being analysed: a nested function body, or the surrounding block code.

    Note on "the surrounding block code": currently it catches jumps onto a trailing `SetMember`,
    which in reality should resolve to `LEAVES_FUNCTION`. The model does not detect that case, and
    letting it into `UNRESOLVED` is conservative.
    """


def resolve_branch_target(
    line: PcodeInstruction, label_targets: dict[str, int], block_labels: set[str]
) -> int | BranchResolution:
    """
    Resolve a branch instruction to a line within the same scope, or signal why it cannot be.

    See `BranchResolution`.
    """
    if len(line.operands) != 1 or line.operands[0].type != "symbol":
        return BranchResolution.UNRESOLVED

    label = str(line.operands[0].value).lower()

    if label in label_targets:
        return label_targets[label]

    if label in block_labels:
        return BranchResolution.UNRESOLVED

    return BranchResolution.LEAVES_FUNCTION


def build_function_scope_control_flow(
    lines: list[PcodeLine], scope_start_idx: int, scope_end_idx: int
) -> tuple[dict[int, list[int]], set[int]]:
    """
    Build a successor map over the function scope.

    Nested function bodies are stepped over: defining a function does not execute it, so control
    flows from the definition to whatever follows its closing brace.
    """
    # First collect every label definition _anywhere in the block_.
    # It will be used to tell a branch apart from one that leaves the block, because labels that
    # this scope does not own (a nested body's, or any surrounding block code etc.) are not exits.
    block_labels: set[str] = {line.label.lower() for line in lines if line.label is not None}

    # Then collect label definitions within the function scope (and their line indices).
    label_targets: dict[str, int] = {}

    # Also collect indices of flow graph nodes.
    nodes: list[int] = []

    i = scope_start_idx + 1  # start right after the function header

    # Exclude the closing brace, because control leaves the function there,
    # so it is not a node of the flow graph.
    while i < scope_end_idx:
        line = lines[i]

        if line.label is not None:
            label_targets[line.label.lower()] = i

        # Accept closing braces (PcodeStructural) as nodes when they have a label (even though it should never happen).
        if is_pcode_instruction(line) or line.label is not None:
            nodes.append(i)

        # Step over nested functions.
        if is_pcode_instruction(line) and line.is_function_definition():
            i = find_scope_end_line(lines, i) + 1
            continue

        i += 1

    # Map every node to its immediate follower node index.
    # It sounds trivial but it is NOT, because `nodes` has gaps, wherever a nested function body
    # or a closing brace was stepped over.
    follower: dict[int, int] = {idx: nodes[pos + 1] for pos, idx in enumerate(nodes) if pos + 1 < len(nodes)}

    successors: dict[int, list[int]] = {}
    unresolved_branches: set[int] = set()

    for idx in nodes:
        line = lines[idx]

        # No follower means the next line is the closing brace and control leaves the function.
        fallthrough = [follower[idx]] if idx in follower else []

        if not is_pcode_instruction(line):
            # In this context, a non-instruction is a closing brace, or a blank line, with a label.
            successors[idx] = fallthrough
            continue

        if line.opcode == "Return":
            successors[idx] = []
        elif line.opcode in OPAQUE_CONTROL_FLOW_OPCODES:
            unresolved_branches.add(idx)
            successors[idx] = []
        elif line.opcode in ["Jump", "If"]:
            target = resolve_branch_target(line, label_targets, block_labels)

            if target is BranchResolution.UNRESOLVED:
                unresolved_branches.add(idx)
                taken = []
            elif target is BranchResolution.LEAVES_FUNCTION:
                taken = []
            else:
                taken = [target]

            if line.opcode == "Jump":  # Jump is unconditional
                successors[idx] = taken
            else:
                successors[idx] = taken + fallthrough
        else:
            successors[idx] = fallthrough

    return successors, unresolved_branches


def line_reads_register(line: PcodeLine, register_index: str) -> bool:
    """
    Determine whether the line reads the given register.
    """
    if not is_pcode_instruction(line):
        return False

    for operand in line.operands:
        if operand.type != "symbol":
            continue

        match = REGISTER_REFERENCE_RE.fullmatch(str(operand.value))

        if match is not None and match.group("regindex") == register_index:
            return True

    return False


def line_writes_register(line: PcodeLine, register_index: str) -> bool:
    """
    Determine whether the line writes the given register.
    """
    return bool(
        is_pcode_instruction(line)
        and line.opcode == "StoreRegister"
        and line.operands
        and line.operands[0].type == "numeric"
        and str(line.operands[0].value) == register_index
    )


def undefined_initializer_could_be_read(
    lines: list[PcodeLine], successors: dict[int, list[int]], unresolved_branches: set[int], triple_idx: int
) -> bool:
    """
    Determine whether any execution path after the initialization could reach a read of `registerN`
    before it is overwritten.

    Every path is pruned at the first write, because beyond it the `undefined` value is gone anyway.
    Conversely, reaching a read means that the initial value can be observed, so the initializer
    carries meaning.

    Paths leaving the function resolve to "no read", assuming the registers go away with the function execution.
    Conservatively, a branch that the control-flow model could not make sense of counts as reading the value.
    """
    store_reg_line = lines[triple_idx + 1]
    assert is_pcode_instruction(store_reg_line)
    register_index = str(store_reg_line.operands[0].value)

    pending = list(successors.get(triple_idx + 2, []))
    visited: set[int] = set()

    while pending:
        idx = pending.pop()

        if idx in visited:
            continue

        visited.add(idx)

        if idx in unresolved_branches:
            return True  # control goes somewhere unmodelled => conservatively assume it could be read

        line = lines[idx]

        if line_reads_register(line, register_index):
            return True

        if line_writes_register(line, register_index):
            # The register is overwritten, so its initial value is dead from this point on.
            # No need to continue on this path.
            continue

        pending.extend(successors.get(idx, []))

    return False


def drop_lines_preserving_sources(lines: list[PcodeLine], to_drop: set[int]) -> list[PcodeLine]:
    """
    Drop lines by index while keeping their raw p-code `source_lines` attached to a surviving neighbour.

    Rendering derives a block's source span from its first and last line, so a dropped mapping is
    merged backwards into the previous survivor, or forwards into the next survivor when the drop
    happens at the very start of the block.
    """
    kept: list[PcodeLine] = []  # lines kept so far
    last_dropped: list[PcodeLine] = []  # latest run of lines that we dropped

    for i, line in enumerate(lines):
        if i in to_drop:
            last_dropped.append(line)
            continue

        # If we keep the current line and we have just dropped previous lines.
        if last_dropped:
            if kept:
                # Attach source lines to the latest kept line.
                kept[-1] = kept[-1].replace(source_lines=merge_pcode_lines_sources(kept[-1], *last_dropped))
            else:
                # Attach source lines to the current (kept) line.
                line = line.replace(source_lines=merge_pcode_lines_sources(line, *last_dropped))

            last_dropped = []

        kept.append(line)

    # Sources of lines dropped at the end of the block are attached to the last kept line.
    if last_dropped and kept:
        kept[-1] = kept[-1].replace(source_lines=merge_pcode_lines_sources(kept[-1], *last_dropped))

    return kept


def strip_dead_undefined_register_initializers(lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Remove `Push undefined` / `StoreRegister N` / `Pop` triples from a v2 function's prologue
    when no observable read can depend on the `undefined` value they set.

    These explicit initializations are usually an artifact of decompilation/recompilation with ffdec.

    This pass only handles `DefineFunction2` functions, because the control-flow analysis relies on registers
    being private to each call. `DefineFunction` registers are shared/global, so their triples are kept.
    So are triples in a `DefineFunction2` whose register index is at or above the function's register count,
    as that could target a shared/global register too.
    Ruffle, an open-source Flash Player emulator written in Rust, implements AVM1 registers this way:
    - https://github.com/ruffle-rs/ruffle/blob/f24403b5a801b442750241f0eb0806d1c28f7561/core/src/avm1/runtime.rs#L71-L73
    - https://github.com/ruffle-rs/ruffle/blob/f24403b5a801b442750241f0eb0806d1c28f7561/swf/src/avm1/types.rs#L131-L150
    - https://github.com/ruffle-rs/ruffle/blob/f24403b5a801b442750241f0eb0806d1c28f7561/core/src/avm1/activation.rs#L2489-L2503

    Example:
        DefineFunction2 "findCloud", 2, 6, false, false, true, false, true, ... {
        Push undefined
        StoreRegister 3
        Pop
        ...

    The scope is the *outer* function of the block only; nested functions are left alone.
    A triple is kept whenever control flow is ambiguous.

    Caveat: it must run *before* `canonicalize_function_definition_headers`, which erases the difference
    between `DefineFunction` and `DefineFunction2`.
    It must also run *before* `canonicalize_register_references_in_function_block` to ensure that
    the potential gaps created by dropping `StoreRegister` instructions get closed.
    """
    scope = find_outer_function_boundaries(lines)

    if scope is None:
        return lines  # not a function block => no prologue, keep everything untouched

    scope_start_idx, scope_end_idx = scope
    outer_function_header = lines[scope_start_idx]
    assert is_pcode_instruction(outer_function_header)

    if outer_function_header.opcode != "DefineFunction2":
        return lines  # the outermost function is a v1 function: give up

    initializer_triples = find_prologue_undefined_initializers(lines, scope_start_idx, scope_end_idx)

    if not initializer_triples:
        return lines

    successors, unresolved_branches = build_function_scope_control_flow(lines, scope_start_idx, scope_end_idx)
    register_count = int(outer_function_header.operands[2].value)

    to_drop: set[int] = set()

    for triple_idx in initializer_triples:
        store_register = lines[triple_idx + 1]
        assert is_pcode_instruction(store_register)

        if int(store_register.operands[0].value) >= register_count:
            continue  # not a private register

        if undefined_initializer_could_be_read(lines, successors, unresolved_branches, triple_idx):
            continue

        to_drop.update({triple_idx, triple_idx + 1, triple_idx + 2})

    if not to_drop:
        return lines

    return drop_lines_preserving_sources(lines, to_drop)


def normalize_block(block: PcodeBlock) -> PcodeBlock:
    """
    Normalize a p-code block with multiple obscure techniques.
    """
    lines = block.lines
    lines = canonicalize_push_lines(lines)
    lines = canonicalize_numeric_literals(lines)
    lines = strip_dead_undefined_register_initializers(lines)
    lines = canonicalize_function_definition_headers(lines)
    lines = canonicalize_register_references_in_function_block(lines)
    lines = strip_unreferenced_label_definitions(lines)
    lines = canonicalize_labels(lines)
    lines = normalize_not_not_if_patterns(lines)
    lines = canonicalize_increment_decrement_patterns(lines)
    lines = canonicalize_constant_pool(lines)
    lines = canonicalize_string_concatenation(lines)
    lines = canonicalize_geturl2(lines)

    return PcodeBlock(lines=lines, name=block.name)


@dataclass(frozen=True)
class NormalizationResult:
    blocks: list[PcodeBlock]
    total_blocks: int
    named_blocks: int
    anonymous_blocks: int
    toplevel_blocks: int


def normalize_file(input_file: Path, output_dir: Path, write_source_maps: bool = True) -> NormalizationResult:
    """
    Split a p-code file into multiple normalized blocks and write them in the output directory.
    """
    pcode_file = parse_pcode_file(input_file)
    blocks = [normalize_block(block) for block in split_into_blocks(pcode_file)]

    output_dir.mkdir(parents=True, exist_ok=True)

    named_count = anon_count = gap_count = 0
    block_order: list[str] = []

    for block in blocks:
        assert block.name is not None
        block_file = output_dir / f"{block.name}.pcode"
        block_file.write_text(block.render() + "\n", encoding="utf-8")

        if write_source_maps:
            block_sourcemap = [ln.source_lines for ln in block.lines]
            block_sourcemap_file = output_dir / f"{block.name}.pcode.map"
            block_sourcemap_file.write_text(json.dumps(block_sourcemap) + "\n", encoding="utf-8")

        block_order.append(block.name)

        if block.name.startswith("__toplevel"):
            gap_count += 1
        elif block.name.startswith("__anonymous"):
            anon_count += 1
        else:
            named_count += 1

    (output_dir / "order.txt").write_text("\n".join(block_order), encoding="utf-8")

    return NormalizationResult(
        blocks=blocks,
        total_blocks=len(blocks),
        named_blocks=named_count,
        anonymous_blocks=anon_count,
        toplevel_blocks=gap_count,
    )
