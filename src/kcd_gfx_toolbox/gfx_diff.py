from __future__ import annotations
from dataclasses import dataclass, field
from difflib import unified_diff
from enum import StrEnum
from pathlib import Path
from typing import cast
from .utils import list_tree_files, read_file_lines
from .avm1.pcode_alignment import align_labels_in_text, align_registers_in_text
from .file_diff import FileDiff, TextDiffSpan, diff_file_trees, diff_texts, format_path_rename_git_style


@dataclass(frozen=True)
class GfxScript:
    """
    One diff entry for a script.

    Contains the script path on side A and/or side B.
    """

    side_a_path: Path | None = None
    side_b_path: Path | None = None

    def __post_init__(self):
        if self.side_a_path is None and self.side_b_path is None:
            raise ValueError("At least one of 'side_a_path' or 'side_b_path' must be defined.")

    def is_paired(self) -> bool:
        return self.side_a_path is not None and self.side_b_path is not None

    def was_renamed(self) -> bool:
        return self.is_paired() and self.side_a_path != self.side_b_path

    def __repr__(self):
        if self.side_a_path is None:
            path_text = format_path_rename_git_style(self.side_b_path, None)
        else:
            path_text = format_path_rename_git_style(self.side_a_path, self.side_b_path)
        return f"{self.__class__.__name__}('{path_text}')"


class GfxDiffSet:
    """
    Container for diff information: common scripts that differ and script only on one side.
    """

    def __init__(self):
        self.paired_scripts: set[GfxScript] = set()
        self.unmatched_a_scripts: set[GfxScript] = set()
        self.unmatched_b_scripts: set[GfxScript] = set()
        self.paired_scripts_block_diffs: dict[GfxScript, ScriptDiffSet] = {}

    def is_empty(self) -> bool:
        return not self.get_differing_scripts()

    def set_script_block_diff(
        self,
        script: GfxScript,
        file_diffs: list[FileDiff],
        only_in_tree_a: list[Path],
        only_in_tree_b: list[Path],
    ):
        if script not in self.paired_scripts:
            raise ValueError(f"Script path '{script}' is unknown.")

        for fd in file_diffs:
            self.paired_scripts_block_diffs.setdefault(script, ScriptDiffSet()).paired_blocks.add(
                # Convert FileDiff to GfxScriptBlock
                GfxScriptBlock(
                    side_a_name=fd.path.stem,
                    changed=fd.lines_changed,
                    side_b_name=fd.path_new.stem if fd.path_new else fd.path.stem,
                    diff_spans=fd.spans,
                )
            )

        for path in only_in_tree_a:
            self.paired_scripts_block_diffs.setdefault(script, ScriptDiffSet()).unmatched_a_blocks.add(
                GfxScriptBlock(side_a_name=path.stem, side_b_name=None)
            )

        for path in only_in_tree_b:
            self.paired_scripts_block_diffs.setdefault(script, ScriptDiffSet()).unmatched_b_blocks.add(
                GfxScriptBlock(side_a_name=None, side_b_name=path.stem)
            )

    def get_differing_scripts(self) -> set[GfxScript]:
        return self.get_scripts_with_differing_blocks() | self.unmatched_a_scripts | self.unmatched_b_scripts

    def get_scripts_with_differing_blocks(self) -> set[GfxScript]:
        return {
            script
            for script, script_diffset in self.paired_scripts_block_diffs.items()
            if script_diffset.has_differing_blocks()
        }

    def get_modified_block_count(self) -> int:
        count = 0

        for details in self.paired_scripts_block_diffs.values():
            # Ignore pure renames.
            count += sum(1 for bch in details.paired_blocks if bch.changed > 0)

        return count

    def get_modified_block_line_count(self) -> int:
        return sum(sum(bc.changed for bc in det.paired_blocks) for det in self.paired_scripts_block_diffs.values())

    def get_unmatched_block_side_a_count(self) -> int:
        return sum(len(det.unmatched_a_blocks) for det in self.paired_scripts_block_diffs.values())

    def get_unmatched_block_side_b_count(self) -> int:
        return sum(len(det.unmatched_b_blocks) for det in self.paired_scripts_block_diffs.values())

    def to_tree(self) -> GfxDiffTreeNode:
        return build_diff_tree(self)

    def __rich_repr__(self):
        yield from self.__dict__.items()


@dataclass(unsafe_hash=True)
class GfxScriptBlock:
    """
    One diff entry for a script block.
    """

    side_a_name: str | None = field(default=None, hash=True)
    side_b_name: str | None = field(default=None, hash=True)
    changed: int = field(default=0, compare=False)
    diff_spans: list[TextDiffSpan] = field(default_factory=list, compare=False)
    refined_changed: int = field(default=0, compare=False)
    unified_diff: list[str] = field(default_factory=list, compare=False)

    def __post_init__(self):
        if self.side_a_name is None and self.side_b_name is None:
            raise ValueError("At least one of 'side_a_name' or 'side_b_name' must be defined.")

    def is_paired(self) -> bool:
        return self.side_a_name is not None and self.side_b_name is not None

    def was_renamed(self) -> bool:
        return self.is_paired() and self.side_a_name != self.side_b_name


class ScriptDiffSet:
    """
    Block-level diff details for one script.

    It tracks modified blocks and blocks that exist only on side A or side B.
    """

    def __init__(self):
        self.paired_blocks: set[GfxScriptBlock] = set()
        self.unmatched_a_blocks: set[GfxScriptBlock] = set()
        self.unmatched_b_blocks: set[GfxScriptBlock] = set()

    def has_differing_blocks(self) -> bool:
        return (
            any(bch.changed > 0 for bch in self.paired_blocks)
            or bool(self.unmatched_a_blocks)
            or bool(self.unmatched_b_blocks)
        )

    def get_differing_blocks(self) -> set[GfxScriptBlock]:
        return (
            {blk for blk in self.paired_blocks if blk.changed > 0} | self.unmatched_a_blocks | self.unmatched_b_blocks
        )

    def __rich_repr__(self):
        yield from self.__dict__.items()


def _sort_match_candidates_for_script(script_path: Path, unmatched_script_paths: set[Path]) -> list[Path]:
    """
    Get the filtered and sorted pool of match candidates for a given script.
    """
    candidates = []

    for unmatched in sorted(unmatched_script_paths, key=lambda p: p.name):
        # To avoid noisy matching, constrain candidates to the same parent path.
        if unmatched.parent == script_path.parent:
            candidates.append(unmatched)

    if script_path in candidates:
        # Give priority to path identity. Make it the first evaluated candidate.
        candidates.remove(script_path)
        candidates.insert(0, script_path)

    return candidates


def diff_normalized_script_trees(
    a_side_scripts: set[Path],
    b_side_scripts: set[Path],
    normalization_dir_a: Path,
    normalization_dir_b: Path,
) -> GfxDiffSet:
    diffset = GfxDiffSet()

    # For all different scripts in A, find their best match on side B.
    # Even common-path scripts are put back in the pool, because content matching
    # is more important than path matching.
    unmatched_side_a_scripts = a_side_scripts.copy()
    unmatched_side_b_scripts = b_side_scripts.copy()

    MATCH_SIMILARITY_THRESHOLD = 0.9

    for script_path_in_a in sorted(unmatched_side_a_scripts):
        if not unmatched_side_b_scripts:  # if all script on side B have already been matched.
            break

        candidates = _sort_match_candidates_for_script(script_path_in_a, unmatched_side_b_scripts)

        if not candidates:
            continue

        script_normalized_dir = normalization_dir_a / script_path_in_a
        script_blocks_on_side_a = len(list_tree_files(script_normalized_dir, glob="*.pcode"))
        best_match: tuple[float, Path, tuple[list[FileDiff], list[Path], list[Path]]] | None = None

        for candidate in candidates:
            candidate_normalized_dir = normalization_dir_b / candidate
            paired_blocks, only_in_a, only_in_b, equal_blocks = diff_file_trees(
                script_normalized_dir, candidate_normalized_dir, glob="*.pcode"
            )
            similarity = (len(paired_blocks) + len(equal_blocks)) / script_blocks_on_side_a

            if best_match is None or similarity > best_match[0]:
                best_match = (similarity, candidate, (paired_blocks, only_in_a, only_in_b))

            # Give priority to path identity. If similarity is already good enough don't look any further.
            # This relies on `_sort_match_candidates_for_script` putting the same-path candidate first.
            if candidate == script_path_in_a and similarity >= MATCH_SIMILARITY_THRESHOLD:
                break

        best_match = cast(tuple, best_match)  # type narrowing for Pyright to calm down
        similarity, best_candidate, best_candidate_diff = best_match

        if similarity < MATCH_SIMILARITY_THRESHOLD:
            continue

        unmatched_side_b_scripts.discard(best_candidate)
        unmatched_side_a_scripts.discard(script_path_in_a)
        paired_script = GfxScript(side_a_path=script_path_in_a, side_b_path=best_candidate)
        diffset.paired_scripts.add(paired_script)

        diffset.set_script_block_diff(paired_script, *best_candidate_diff)

    diffset.unmatched_a_scripts = {GfxScript(side_a_path=p) for p in unmatched_side_a_scripts}
    diffset.unmatched_b_scripts = {GfxScript(side_b_path=p) for p in unmatched_side_b_scripts}

    return diffset


def refine_block_diffs(diffset: GfxDiffSet, normalization_dir_a: Path, normalization_dir_b: Path) -> GfxDiffSet:
    """
    Apply post-normalization refinement passes to script block diffs to reduce noise
    that per-script normalization alone cannot eliminate.

    Baseline normalization removes most disassembler noise, but any insertion or deletion in p-code
    can cause drift in label and register names, inflating line diffs.
    Re-aligning side B against side A yields more meaningful change counts.
    """
    for script in diffset.get_scripts_with_differing_blocks():
        for block in diffset.paired_scripts_block_diffs[script].paired_blocks:
            if not block.is_paired():
                continue

            block_a = read_file_lines(normalization_dir_a / script.side_a_path / f"{block.side_a_name}.pcode")
            block_b = read_file_lines(normalization_dir_b / script.side_b_path / f"{block.side_b_name}.pcode")

            block_b = align_labels_in_text(block_b, anchor_lines=block_a)
            block_b = align_registers_in_text(block_b, anchor_lines=block_a)
            text_diff = diff_texts(block_a, block_b)
            block.refined_changed = text_diff.lines_changed
            block.unified_diff = list(unified_diff(block_a, block_b))

    return diffset


class GfxDiffTreeNodeType(StrEnum):
    ROOT = "root"
    DIRECTORY = "directory"
    SCRIPT = "script"
    SCRIPT_BLOCK = "script_block"


@dataclass(frozen=True)
class GfxDiffTreeNode:
    type: GfxDiffTreeNodeType
    value: str | GfxScript | GfxScriptBlock | None
    children: set[GfxDiffTreeNode] = field(default_factory=set, compare=False, hash=False)

    def __post_init__(self):
        actual_type = type(self.value).__name__
        if self.type == GfxDiffTreeNodeType.ROOT and self.value is not None:
            raise ValueError(f"Root node must have a None value; got {actual_type}.")
        if self.type == GfxDiffTreeNodeType.DIRECTORY and not isinstance(self.value, str):
            raise ValueError(f"Directory nodes must have a string value; got {actual_type}.")
        if self.type == GfxDiffTreeNodeType.SCRIPT and not isinstance(self.value, GfxScript):
            raise ValueError(f"Script nodes must have a GfxScript value; got {actual_type}.")
        if self.type == GfxDiffTreeNodeType.SCRIPT_BLOCK and not isinstance(self.value, GfxScriptBlock):
            raise ValueError(f"Script block nodes must have a GfxScriptBlock value; got {actual_type}.")

    def find_child(
        self, node_type: GfxDiffTreeNodeType, value: str | GfxScript | GfxScriptBlock
    ) -> GfxDiffTreeNode | None:
        return next((c for c in self.children if c.type == node_type and c.value == value), None)


def build_diff_tree(diffset: GfxDiffSet) -> GfxDiffTreeNode:
    """
    Build a tree structure of `GfxDiffTreeNode` from a diff set.
    """
    root = GfxDiffTreeNode(type=GfxDiffTreeNodeType.ROOT, value=None)

    for script in diffset.get_differing_scripts():
        if script.side_a_path is not None:
            path = script.side_a_path
        else:
            assert script.side_b_path is not None
            path = script.side_b_path

        current_node = root

        for seg in path.parent.parts:
            if not (seg_node := current_node.find_child(GfxDiffTreeNodeType.DIRECTORY, seg)):
                seg_node = GfxDiffTreeNode(type=GfxDiffTreeNodeType.DIRECTORY, value=seg)
                current_node.children.add(seg_node)

            current_node = seg_node

        script_node = GfxDiffTreeNode(type=GfxDiffTreeNodeType.SCRIPT, value=script)
        current_node.children.add(script_node)

        if script not in diffset.paired_scripts_block_diffs:
            continue

        for block in diffset.paired_scripts_block_diffs[script].get_differing_blocks():
            script_node.children.add(GfxDiffTreeNode(type=GfxDiffTreeNodeType.SCRIPT_BLOCK, value=block))

    return root
