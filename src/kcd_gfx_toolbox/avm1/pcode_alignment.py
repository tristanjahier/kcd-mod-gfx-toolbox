import difflib
from collections import Counter, defaultdict

from .pcode_parsing import PcodeBlock, PcodeLine, PcodeOperand, is_pcode_instruction
from .pcode_utils import REGISTER_REFERENCE_RE


def neutralize_labels_in_line(line: PcodeLine) -> PcodeLine:
    """
    Replace label prefix and target label references with `LABEL`, when present.
    """
    label = "LABEL" if line.label is not None else None

    if not is_pcode_instruction(line):
        return line.replace(label=label)

    operands = list(line.operands)  # copy!

    if line.opcode in ["If", "Jump"] and operands:
        operands[0] = PcodeOperand(type="symbol", value="LABEL")

    return line.replace(label=label, operands=operands)


def extract_jump_target_label_from_line(line: PcodeLine) -> str | None:
    """
    Extract the target label of a If/Jump instruction line if any.
    """
    if not is_pcode_instruction(line):
        return None

    if line.opcode in ["If", "Jump"] and line.operands:
        return str(line.operands[0].value)

    return None


def build_label_alignment_map(block_a_lines: list[PcodeLine], block_b_lines: list[PcodeLine]) -> dict[str, str]:
    """
    Build a mapping from labels in block B to their corresponding labels in block A.

    The mapping is built by diffing the two blocks with labels neutralized (label definitions
    and jump targets are replaced with a constant) to maximize alignment on other structures.
    The best one-to-one correspondences between (initially neutralized) labels from both blocks are kept.
    """
    normalized_block_a_lines = [neutralize_labels_in_line(line).render() for line in block_a_lines]
    normalized_block_b_lines = [neutralize_labels_in_line(line).render() for line in block_b_lines]

    # Diff is computed on an aggressively normalized corpus to maximize comparability of blocks.
    seqmatch = difflib.SequenceMatcher(None, normalized_block_a_lines, normalized_block_b_lines, autojunk=False)

    # "Votes" here simply means "occurrences of label correspondence".
    votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])

    # For all structurally equal parts, we collect the label correspondences between original blocks.
    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag != "equal":
            continue

        for k in range(i2 - i1):
            line_k_in_block_a = block_a_lines[i1 + k]
            line_k_in_block_b = block_b_lines[j1 + k]

            label_in_block_a = line_k_in_block_a.label
            label_in_block_b = line_k_in_block_b.label

            if label_in_block_a and label_in_block_b:
                votes[label_in_block_b][label_in_block_a] += 1

            target_label_in_block_a = extract_jump_target_label_from_line(line_k_in_block_a)
            target_label_in_block_b = extract_jump_target_label_from_line(line_k_in_block_b)

            if target_label_in_block_a and target_label_in_block_b:
                votes[target_label_in_block_b][target_label_in_block_a] += 1

    if not votes:
        return {}

    # Pre-compute the inverted index of label correspondences, from block A to block B.
    inverted_votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])
    for label_in_block_b, votes_for_labels_in_block_a in votes.items():
        for label_in_block_a, count in votes_for_labels_in_block_a.items():
            inverted_votes[label_in_block_a][label_in_block_b] = count

    # Keep only reciprocal unique correspondences.
    label_correspondences: list[tuple[int, str, str]] = []

    for label_in_block_b, votes_for_labels_in_block_a in votes.items():
        best_score = max(votes_for_labels_in_block_a.values())
        best_matches_from_block_a = sorted(
            label for label, score in votes_for_labels_in_block_a.items() if score == best_score
        )

        if len(best_matches_from_block_a) != 1:
            # If there is not one clear winner, we don't match.
            continue

        best_match_from_block_a = best_matches_from_block_a[0]

        # Check that `label_in_block_b` is reciprocally the best correspondence for `best_match_from_block_a`.
        votes_for_best_match = inverted_votes[best_match_from_block_a]
        best_score_for_best_match = max(votes_for_best_match.values())

        best_matches_of_best_match = sorted(
            label for label, score in votes_for_best_match.items() if score == best_score_for_best_match and score > 0
        )

        if len(best_matches_of_best_match) != 1 or best_matches_of_best_match[0] != label_in_block_b:
            # If there is not one clear winner, or it is not reciprocal, we don't match either.
            continue

        label_correspondences.append((best_score, label_in_block_b, best_match_from_block_a))

    # By construction, label_correspondences contains only unique pairs, and no labels are shared by multiple pairs.
    return {label_in_block_b: label_in_block_a for _, label_in_block_b, label_in_block_a in label_correspondences}


def remap_labels_in_line(line: PcodeLine, label_map: dict[str, str]) -> PcodeLine:
    """
    Replace labels (prefixes and jump targets) in a line according to the given label map.
    """
    label = label_map.get(line.label, line.label) if line.label is not None else None

    if not is_pcode_instruction(line):
        return line.replace(label=label)

    operands = list(line.operands)  # copy!

    if line.opcode in ["If", "Jump"] and operands:
        old_target = str(line.operands[0].value)
        new_target = label_map.get(old_target, old_target)
        operands[0] = PcodeOperand(type="symbol", value=new_target)

    return line.replace(label=label, operands=operands)


def align_labels(block_a_lines: list[PcodeLine], block_b_lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Rewrite labels (prefixes + jump targets) in `block_b_lines` to align/compare better with `block_a_lines`.
    """
    label_map = build_label_alignment_map(block_a_lines, block_b_lines)

    if not label_map:
        return block_b_lines

    aligned_lines: list[PcodeLine] = []

    for line in block_b_lines:
        aligned_lines.append(remap_labels_in_line(line, label_map))

    return aligned_lines


def neutralize_registers_in_line(line: PcodeLine) -> PcodeLine:
    """
    Replace register references with `registerN` and `StoreRegister N`.
    """
    if not is_pcode_instruction(line):
        return line

    operands = list(line.operands)  # copy!

    if line.opcode in ["Push", "Try"] and operands:
        for i, operand in enumerate(operands):
            if operand.type == "symbol" and REGISTER_REFERENCE_RE.fullmatch(str(operand.value)):
                operands[i] = PcodeOperand(type="symbol", value="registerN")
    elif line.opcode == "StoreRegister":
        operands[0] = PcodeOperand(type="symbol", value="N")  # type "symbol" is unusual for StoreRegister

    return line.replace(operands=operands)


def extract_register_indices_from_line(line: PcodeLine) -> list[int]:
    """
    Extract all register references from a `Push`, `Try` or `StoreRegister` line if any.
    """
    if not is_pcode_instruction(line):
        return []

    registers: list[int] = []

    if line.opcode in ["Push", "Try"] and line.operands:
        for operand in line.operands:
            if operand.type == "symbol" and (match := REGISTER_REFERENCE_RE.fullmatch(str(operand.value))):
                registers.append(int(match.group("regindex")))
    elif line.opcode == "StoreRegister":
        registers.append(int(line.operands[0].value))

    return registers


def build_register_alignment_map(block_a_lines: list[PcodeLine], block_b_lines: list[PcodeLine]) -> dict[int, int]:
    """
    Build a mapping from registers in block B to their corresponding registers in block A.

    The mapping is inferred from structurally equal spans after registers are neutralized.
    Only reciprocal unique correspondences are kept.
    """
    normalized_block_a_lines = [neutralize_registers_in_line(line).render() for line in block_a_lines]
    normalized_block_b_lines = [neutralize_registers_in_line(line).render() for line in block_b_lines]

    # Diff is computed on an aggressively normalized corpus to maximize comparability of blocks.
    seqmatch = difflib.SequenceMatcher(None, normalized_block_a_lines, normalized_block_b_lines, autojunk=False)

    # "Votes" here simply means "occurrences of register correspondence".
    votes: defaultdict[int, Counter[int]] = defaultdict(Counter[int])

    # For all structurally equal parts, we collect the register correspondences between original blocks.
    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag != "equal":
            continue

        for k in range(i2 - i1):
            registers_in_block_a = extract_register_indices_from_line(block_a_lines[i1 + k])
            registers_in_block_b = extract_register_indices_from_line(block_b_lines[j1 + k])

            if registers_in_block_a and registers_in_block_b:
                for reg1 in registers_in_block_a:
                    for reg2 in registers_in_block_b:
                        votes[reg2][reg1] += 1

    if not votes:
        return {}

    # Pre-compute the inverted index of register correspondences, from block A to block B.
    inverted_votes: defaultdict[int, Counter[int]] = defaultdict(Counter[int])
    for register_in_block_b, votes_for_registers_in_block_a in votes.items():
        for register_in_block_a, count in votes_for_registers_in_block_a.items():
            inverted_votes[register_in_block_a][register_in_block_b] = count

    # Keep only reciprocal unique correspondences.
    register_correspondences: list[tuple[int, int, int]] = []

    for register_in_block_b, votes_for_registers_in_block_a in votes.items():
        best_score = max(votes_for_registers_in_block_a.values())
        best_matches_from_block_a = sorted(
            register for register, score in votes_for_registers_in_block_a.items() if score == best_score
        )

        if len(best_matches_from_block_a) != 1:
            # If there is not one clear winner, we don't match.
            continue

        best_match_from_block_a = best_matches_from_block_a[0]

        # Check that `register_in_block_b` is reciprocally the best correspondence for `best_match_from_block_a`.
        votes_for_best_match = inverted_votes[best_match_from_block_a]
        best_score_for_best_match = max(votes_for_best_match.values())

        best_matches_of_best_match = sorted(
            register
            for register, score in votes_for_best_match.items()
            if score == best_score_for_best_match and score > 0
        )

        if len(best_matches_of_best_match) != 1 or best_matches_of_best_match[0] != register_in_block_b:
            # If there is not one clear winner, or it is not reciprocal, we don't match either.
            continue

        register_correspondences.append((best_score, register_in_block_b, best_match_from_block_a))

    # By construction, register_correspondences contains only unique pairs, and no registers are shared by multiple pairs.
    return {
        register_in_block_b: register_in_block_a
        for _, register_in_block_b, register_in_block_a in register_correspondences
    }


def remap_registers_in_line(line: PcodeLine, register_map: dict[int, int]) -> PcodeLine:
    """
    Replace register references in a line according to the given register map.
    """
    if not is_pcode_instruction(line):
        return line

    operands = list(line.operands)  # copy!

    if line.opcode in ["Push", "Try"] and operands:
        for i, operand in enumerate(operands):
            if operand.type == "symbol" and (match := REGISTER_REFERENCE_RE.fullmatch(str(operand.value))):
                old_register = int(match.group("regindex"))
                new_register = register_map.get(old_register, old_register)
                operands[i] = PcodeOperand(type="symbol", value=f"register{new_register}")
    elif line.opcode == "StoreRegister":
        old_register = int(operands[0].value)
        new_register = register_map.get(old_register, old_register)
        operands[0] = PcodeOperand(type="numeric", value=str(new_register))

    return line.replace(operands=operands)


def align_registers(block_a_lines: list[PcodeLine], block_b_lines: list[PcodeLine]) -> list[PcodeLine]:
    """
    Rewrite register references in `block_b_lines` to align/compare better with `block_a_lines`.
    """
    register_map = build_register_alignment_map(block_a_lines, block_b_lines)

    if not register_map:
        return block_b_lines

    aligned_lines: list[PcodeLine] = []

    for line in block_b_lines:
        aligned_lines.append(remap_registers_in_line(line, register_map))

    return aligned_lines


def align_block_b_on_block_a(block_a: PcodeBlock, block_b: PcodeBlock) -> PcodeBlock:
    """
    Align two p-code blocks together with multiple obscure techniques.

    Block A (the first one) is not touched at all, as it is considered the "anchor".
    Block B (the second one) is the one that is modified to maximize its alignment with A.
    Modifications occur on a copy of block B, the argument is not touched itself.
    """
    lines = list(block_b.lines)
    lines = align_labels(block_a.lines, lines)
    lines = align_registers(block_a.lines, lines)

    return PcodeBlock(lines=lines, name=block_b.name)
