from collections import Counter, defaultdict
import difflib
from .pcode_parsing import tokenize_line
from .pcode_utils import (
    LABEL_REFERENCED_LINE_RE,
    PUSH_REGISTER_RE,
    REGISTER_REFERENCE_RE,
    STORE_REGISTER_RE,
    extract_label_from_line,
    strip_label,
)


def neutralize_labels_in_line(line: str) -> str:
    """
    Replace label prefix and target label references with `<LABEL>`, when present.
    """
    normalized_line = ""
    labelless_line, label_prefix = extract_label_from_line(line)

    if label_prefix is not None:
        normalized_line += "<LABEL>: "

    if match := LABEL_REFERENCED_LINE_RE.match(labelless_line):
        normalized_line += match.group("opcode") + " <LABEL>"
    else:
        normalized_line += labelless_line

    return normalized_line


def extract_jump_target_label_from_line(line: str) -> str | None:
    """
    Extract the target label of a If/Jump instruction line if any.
    """
    if match := LABEL_REFERENCED_LINE_RE.match(strip_label(line).strip()):
        return match.group("label")

    return None


def build_label_alignment_map(text1_lines: list[str], text2_lines: list[str]) -> dict[str, str]:
    """
    Build a mapping from labels in text 2 to their corresponding labels in text 1.

    The mapping is built by diffing the two texts with labels neutralized (label definitions
    and jump targets are replaced with a constant) to maximize alignment on other structures.
    The best one-to-one correspondences between (initially neutralized) labels from both texts are kept.
    """
    normalized_text1_lines = [neutralize_labels_in_line(line) for line in text1_lines]
    normalized_text2_lines = [neutralize_labels_in_line(line) for line in text2_lines]

    # Diff is computed on an aggressively normalized corpus to maximize comparability of texts.
    seqmatch = difflib.SequenceMatcher(None, normalized_text1_lines, normalized_text2_lines, autojunk=False)

    # "Votes" here simply means "occurrences of label correspondence".
    votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])

    # For all structurally equal parts, we collect the label correspondences between original texts.
    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag != "equal":
            continue

        for k in range(i2 - i1):
            line_k_in_text1 = text1_lines[i1 + k]
            line_k_in_text2 = text2_lines[j1 + k]

            _, label_in_text1 = extract_label_from_line(line_k_in_text1)
            _, label_in_text2 = extract_label_from_line(line_k_in_text2)

            if label_in_text1 and label_in_text2:
                votes[label_in_text2][label_in_text1] += 1

            target_label_in_text1 = extract_jump_target_label_from_line(line_k_in_text1)
            target_label_in_text2 = extract_jump_target_label_from_line(line_k_in_text2)

            if target_label_in_text1 and target_label_in_text2:
                votes[target_label_in_text2][target_label_in_text1] += 1

    if not votes:
        return {}

    # Pre-compute the inverted index of label correspondences, from text 1 to text 2.
    inverted_votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])
    for label_in_text2, votes_for_labels_in_text1 in votes.items():
        for label_in_text1, count in votes_for_labels_in_text1.items():
            inverted_votes[label_in_text1][label_in_text2] = count

    # Keep only reciprocal unique correspondences.
    label_correspondences: list[tuple[int, str, str]] = []

    for label_in_text2, votes_for_labels_in_text1 in votes.items():
        best_score = max(votes_for_labels_in_text1.values())
        best_matches_from_text1 = sorted(
            label for label, score in votes_for_labels_in_text1.items() if score == best_score
        )

        if len(best_matches_from_text1) != 1:
            # If there is not one clear winner, we don't match.
            continue

        best_match_from_text1 = best_matches_from_text1[0]

        # Check that `label_in_text2` is reciprocally the best correspondence for `best_match_from_text1`.
        votes_for_best_match = inverted_votes[best_match_from_text1]
        best_score_for_best_match = max(votes_for_best_match.values())

        best_matches_of_best_match = sorted(
            label for label, score in votes_for_best_match.items() if score == best_score_for_best_match and score > 0
        )

        if len(best_matches_of_best_match) != 1 or best_matches_of_best_match[0] != label_in_text2:
            # If there is not one clear winner, or it is not reciprocal, we don't match either.
            continue

        label_correspondences.append((best_score, label_in_text2, best_match_from_text1))

    # By construction, label_correspondences contains only unique pairs, and no labels are shared by multiple pairs.
    return {label_in_text2: label_in_text1 for _, label_in_text2, label_in_text1 in label_correspondences}


def remap_labels_in_line(line: str, label_map: dict[str, str]) -> str:
    """
    Replace labels (prefixes and jump targets) in a line according to the given label map.
    """
    labelless_line, label_prefix = extract_label_from_line(line)

    new_label_prefix = label_map.get(label_prefix, label_prefix) if label_prefix is not None else None

    if match := LABEL_REFERENCED_LINE_RE.match(labelless_line.strip()):
        old_target = match.group("label")
        new_target = label_map.get(old_target)
        if new_target is not None:
            return (
                f"{new_label_prefix + ':' if new_label_prefix is not None else ''}{match.group('opcode')} {new_target}"
            )

    if new_label_prefix is not None and new_label_prefix != label_prefix:
        return new_label_prefix + ":" + labelless_line

    return line


def align_labels_in_text(text_lines: list[str], anchor_lines: list[str]) -> list[str]:
    """
    Rewrite labels (prefixes + jump targets) in `text_lines` to align/compare better with `anchor_lines`.
    """
    label_map = build_label_alignment_map(anchor_lines, text_lines)

    if not label_map:
        return text_lines

    aligned_lines: list[str] = []

    for line in text_lines:
        aligned_lines.append(remap_labels_in_line(line, label_map))

    return aligned_lines


def neutralize_registers_in_line(line: str) -> str:
    """
    Replace register references with `registerN` and `StoreRegister N`.
    """
    labelless_line, label_prefix = extract_label_from_line(line)

    if PUSH_REGISTER_RE.match(labelless_line):
        tokens = tokenize_line(labelless_line)
        register_tokens = [tok for tok in tokens if REGISTER_REFERENCE_RE.fullmatch(tok[1])]
        for pos, reg_tok in reversed(register_tokens):
            labelless_line = labelless_line[:pos] + "registerN" + labelless_line[pos + len(reg_tok) :]
        return f"{label_prefix + ':' if label_prefix else ''}{labelless_line}"

    if STORE_REGISTER_RE.match(labelless_line):
        labelless_line = STORE_REGISTER_RE.sub(
            lambda m: m.string[: m.start("regindex")] + "N" + m.string[m.end("regindex") :], labelless_line
        )
        return f"{label_prefix + ':' if label_prefix else ''}{labelless_line}"

    return line


def extract_registers_from_line(line: str) -> list[str]:
    """
    Extract all register references from a `Push` or `StoreRegister` line if any.
    """
    line = strip_label(line)

    if PUSH_REGISTER_RE.match(line):
        tokens = tokenize_line(line)
        return [tok[1] for tok in tokens if REGISTER_REFERENCE_RE.fullmatch(tok[1])]

    if match := STORE_REGISTER_RE.match(line):
        return ["register" + match.group("regindex")]

    return []


def build_register_alignment_map(text1_lines: list[str], text2_lines: list[str]) -> dict[str, str]:
    """
    Build a mapping from registers in text 2 to their corresponding registers in text 1.

    The mapping is inferred from structurally equal spans after registers are neutralized.
    Only reciprocal unique correspondences are kept.
    """
    normalized_text1_lines = [neutralize_registers_in_line(line) for line in text1_lines]
    normalized_text2_lines = [neutralize_registers_in_line(line) for line in text2_lines]

    # Diff is computed on an aggressively normalized corpus to maximize comparability of texts.
    seqmatch = difflib.SequenceMatcher(None, normalized_text1_lines, normalized_text2_lines, autojunk=False)

    # "Votes" here simply means "occurrences of register correspondence".
    votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])

    # For all structurally equal parts, we collect the register correspondences between original texts.
    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag != "equal":
            continue

        for k in range(i2 - i1):
            registers_in_text1 = extract_registers_from_line(text1_lines[i1 + k])
            registers_in_text2 = extract_registers_from_line(text2_lines[j1 + k])

            if registers_in_text1 and registers_in_text2:
                for reg1 in registers_in_text1:
                    for reg2 in registers_in_text2:
                        votes[reg2][reg1] += 1

    if not votes:
        return {}

    # Pre-compute the inverted index of register correspondences, from text 1 to text 2.
    inverted_votes: defaultdict[str, Counter[str]] = defaultdict(Counter[str])
    for register_in_text2, votes_for_registers_in_text1 in votes.items():
        for register_in_text1, count in votes_for_registers_in_text1.items():
            inverted_votes[register_in_text1][register_in_text2] = count

    # Keep only reciprocal unique correspondences.
    register_correspondences: list[tuple[int, str, str]] = []

    for register_in_text2, votes_for_registers_in_text1 in votes.items():
        best_score = max(votes_for_registers_in_text1.values())
        best_matches_from_text1 = sorted(
            register for register, score in votes_for_registers_in_text1.items() if score == best_score
        )

        if len(best_matches_from_text1) != 1:
            # If there is not one clear winner, we don't match.
            continue

        best_match_from_text1 = best_matches_from_text1[0]

        # Check that `register_in_text2` is reciprocally the best correspondence for `best_match_from_text1`.
        votes_for_best_match = inverted_votes[best_match_from_text1]
        best_score_for_best_match = max(votes_for_best_match.values())

        best_matches_of_best_match = sorted(
            register
            for register, score in votes_for_best_match.items()
            if score == best_score_for_best_match and score > 0
        )

        if len(best_matches_of_best_match) != 1 or best_matches_of_best_match[0] != register_in_text2:
            # If there is not one clear winner, or it is not reciprocal, we don't match either.
            continue

        register_correspondences.append((best_score, register_in_text2, best_match_from_text1))

    # By construction, register_correspondences contains only unique pairs, and no registers are shared by multiple pairs.
    return {
        register_in_text2: register_in_text1 for _, register_in_text2, register_in_text1 in register_correspondences
    }


def remap_registers_in_line(line: str, register_map: dict[str, str]) -> str:
    """
    Replace register references in a line according to the given register map.
    """
    labelless_line, label_prefix = extract_label_from_line(line)

    if match := PUSH_REGISTER_RE.match(labelless_line):
        old_registers = extract_registers_from_line(labelless_line)
        new_registers = [register_map[reg] for reg in old_registers if reg in register_map]

        if not new_registers:
            return line

        tokens = tokenize_line(labelless_line)
        replacements: list[tuple[tuple[int, str], str]] = [
            (tok, register_map[tok[1]])
            for tok in tokens
            if REGISTER_REFERENCE_RE.fullmatch(tok[1]) and tok[1] in register_map
        ]

        for (pos, original), replacement in reversed(replacements):
            labelless_line = labelless_line[:pos] + replacement + labelless_line[pos + len(original) :]

        return f"{label_prefix + ':' if label_prefix else ''}{labelless_line}"

    if match := STORE_REGISTER_RE.match(labelless_line):
        old_register = "register" + match.group("regindex")
        if old_register not in register_map:
            return line

        new_register = register_map[old_register]
        new_regindex = new_register.replace("register", "")

        labelless_line = STORE_REGISTER_RE.sub(
            lambda m: m.string[: m.start("regindex")] + new_regindex + m.string[m.end("regindex") :], labelless_line
        )

        return f"{label_prefix + ':' if label_prefix else ''}{labelless_line}"

    return line


def align_registers_in_text(text_lines: list[str], anchor_lines: list[str]) -> list[str]:
    """
    Rewrite register references in `text_lines` to align/compare better with `anchor_lines`.
    """
    register_map = build_register_alignment_map(anchor_lines, text_lines)

    if not register_map:
        return text_lines

    aligned_lines: list[str] = []

    for line in text_lines:
        aligned_lines.append(remap_registers_in_line(line, register_map))

    return aligned_lines
