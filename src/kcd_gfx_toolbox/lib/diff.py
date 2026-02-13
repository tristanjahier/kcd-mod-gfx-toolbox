from dataclasses import dataclass
import difflib
from pathlib import Path
from .util import list_tree_files, read_file_lines, sha256_file


@dataclass(frozen=True)
class FileChange:
    """
    A small container object for file changes.
    """

    path: Path
    changed: int


def diff_file_trees_basic(dir1: Path, dir2: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """
    Perform a basic diff between two directories and their subtrees.
    Return a tuple of:
        1. file paths only present in directory 1
        2. file paths only present in directory 2
        3. file paths in common but with different contents
    """
    dir1_files = list_tree_files(dir1)
    dir2_files = list_tree_files(dir2)

    only_in_dir1 = sorted(dir1_files - dir2_files)
    only_in_dir2 = sorted(dir2_files - dir1_files)
    common = sorted(dir1_files & dir2_files)

    different: list[Path] = []

    for rel_path in common:
        file1 = dir1 / rel_path
        file2 = dir2 / rel_path

        # Fast check on file size.
        if file1.stat().st_size != file2.stat().st_size:
            different.append(rel_path)
            continue

        # Same size: compare hashes.
        if sha256_file(file1) != sha256_file(file2):
            different.append(rel_path)

    return only_in_dir1, only_in_dir2, different


def diff_texts(text1_lines: list[str], text2_lines: list[str]) -> int:
    """
    Compare two sets of text lines.
    Return number of touched lines (inserted, deleted or replaced),
    counting replacements as max(old_span, new_span).
    """
    seqmatch = difflib.SequenceMatcher(None, text1_lines, text2_lines, autojunk=False)
    changed = 0

    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag == "equal":
            continue

        # i1:i2 is the line range in text 1.
        # j1:j2 is the line range in text 2.
        span_1 = i2 - i1
        span_2 = j2 - j1

        if tag == "replace":
            changed += max(span_1, span_2)
        elif tag == "delete":
            changed += span_1
        elif tag == "insert":
            changed += span_2

    return changed


def diff_file_trees(
    dir1: Path,
    dir2: Path,
    include_paths: list[Path] | None = None,
) -> tuple[list[Path], list[Path], list[FileChange]]:
    """
    Perform a diff between two directories and their subtrees.
    Return a tuple of:
        1. file paths only present in directory 1
        2. file paths only present in directory 2
        3. file change stats for common file paths
    """
    dir1_files = list_tree_files(dir1)
    dir2_files = list_tree_files(dir2)

    if include_paths:

        def keep_path(p: Path) -> bool:
            return any(p.is_relative_to(path) for path in include_paths)

        dir1_files = {p for p in dir1_files if keep_path(p)}
        dir2_files = {p for p in dir2_files if keep_path(p)}

    only_in_dir1 = sorted(dir1_files - dir2_files)
    only_in_dir2 = sorted(dir2_files - dir1_files)
    common = sorted(dir1_files & dir2_files)

    changes: list[FileChange] = []

    for rel_path in common:
        file1 = dir1 / rel_path
        file2 = dir2 / rel_path

        # Ignore identical files.
        if file1.stat().st_size == file2.stat().st_size and sha256_file(file1) == sha256_file(file2):
            continue

        file1_lines = read_file_lines(file1)
        file2_lines = read_file_lines(file2)
        changed = diff_texts(file1_lines, file2_lines)

        if changed > 0:
            changes.append(FileChange(path=rel_path, changed=changed))

    return only_in_dir1, only_in_dir2, changes
