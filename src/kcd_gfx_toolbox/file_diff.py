from dataclasses import dataclass
import difflib
from pathlib import Path
from .utils import list_tree_files, read_file_lines, sha256_file


@dataclass(frozen=True)
class FileChange:
    """
    A small container object for file changes.
    """

    path: Path
    changed: int
    path_new: Path | None = None


def diff_file_trees_basic(dir1: Path, dir2: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """
    Perform a basic diff between two directories and their subtrees.
    Return a tuple of:
        1. file paths in common but with different contents
        2. file paths only present in directory 1
        3. file paths only present in directory 2
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

    return different, only_in_dir1, only_in_dir2


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
    include_paths: set[Path] | None = None,
) -> tuple[list[FileChange], list[Path], list[Path], list[Path]]:
    """
    Perform a diff between two directories and their subtrees.
    Return a tuple of:
        1. file change stats for common file paths and paired moved/renamed paths
        2. file paths only present in directory 1
        3. file paths only present in directory 2
        4. equal files (same path, same content)
    """
    dir1_files = list_tree_files(dir1)
    dir2_files = list_tree_files(dir2)

    if include_paths:

        def keep_path(p: Path) -> bool:
            return any(p.is_relative_to(path) for path in include_paths)

        dir1_files = {p for p in dir1_files if keep_path(p)}
        dir2_files = {p for p in dir2_files if keep_path(p)}

    common = sorted(dir1_files & dir2_files)

    changes: list[FileChange] = []

    equals: list[Path] = []

    for rel_path in common:
        file1 = dir1 / rel_path
        file2 = dir2 / rel_path

        # Put aside identical files.
        if file1.stat().st_size == file2.stat().st_size and sha256_file(file1) == sha256_file(file2):
            equals.append(rel_path)
            continue

        file1_lines = read_file_lines(file1)
        file2_lines = read_file_lines(file2)
        changed = diff_texts(file1_lines, file2_lines)

        if changed > 0:
            changes.append(FileChange(path=rel_path, changed=changed))

    # Now we need to take care of unmatched paths on both sides.
    # The most common case is that a path has been renamed, but the file is the same.
    unmatched_dir1 = set(dir1_files - dir2_files)
    unmatched_dir2 = set(dir2_files - dir1_files)

    # Identify and match pure renames by files hashes.
    unmatched_dir1_hashes: dict[Path, str] = {}
    unmatched_dir2_hashes: dict[Path, str] = {}

    for rel_path in unmatched_dir1:
        unmatched_dir1_hashes[rel_path] = sha256_file(dir1 / rel_path)

    for rel_path in unmatched_dir2:
        unmatched_dir2_hashes[rel_path] = sha256_file(dir2 / rel_path)

    common_hashes = set(unmatched_dir1_hashes.values()) & set(unmatched_dir2_hashes.values())

    for file_hash in common_hashes:
        paths_in_dir1 = [p for p, h in unmatched_dir1_hashes.items() if h == file_hash]
        paths_in_dir2 = [p for p, h in unmatched_dir2_hashes.items() if h == file_hash]

        # Note: the following pairing logic is "non-existent". We simply discard the same
        # number of identical files (by hash) on each side.
        # It would probably be better for reporting to pair the "closest" paths.
        paired_count = min(len(paths_in_dir1), len(paths_in_dir2))
        paired_exact_matches = list(zip(paths_in_dir1[:paired_count], paths_in_dir2[:paired_count]))

        for p1, p2 in paired_exact_matches:
            unmatched_dir1.discard(p1)
            unmatched_dir2.discard(p2)

            # Pure rename change.
            changes.append(FileChange(path=p1, path_new=p2, changed=0))

    # Finally, try to pair files with different paths and whose contents are
    # not identical but highly similar and therefore comparable (worth a diff).

    # Caches for file contents.
    file_cache: dict[Path, list[str]] = {}

    def read_file_from_dir1(rel_path: Path) -> list[str]:
        full_path = dir1 / rel_path
        if full_path not in file_cache:
            file_cache[full_path] = read_file_lines(full_path)
        return file_cache[full_path]

    def read_file_from_dir2(rel_path: Path) -> list[str]:
        full_path = dir2 / rel_path
        if full_path not in file_cache:
            file_cache[full_path] = read_file_lines(full_path)
        return file_cache[full_path]

    MATCH_SIMILARITY_THRESHOLD = 0.9

    for path_in_dir1 in sorted(unmatched_dir1):
        if not unmatched_dir2:  # if there is no unmatched file left in dir 2
            break

        # Rank candidates by path similarity first to reduce expensive content comparisons.
        # Keep only the N top candidates (value could be adjusted).
        candidates = sorted(unmatched_dir2, key=lambda p: p.name)

        candidates = sorted(
            candidates,
            key=lambda p: difflib.SequenceMatcher(a=str(path_in_dir1), b=str(p), autojunk=False).ratio(),
            reverse=True,
        )[:20]

        file1_lines = read_file_from_dir1(path_in_dir1)
        best_match: tuple[float, Path] | None = None

        for candidate in candidates:
            similarity = difflib.SequenceMatcher(
                a=file1_lines, b=read_file_from_dir2(candidate), autojunk=False
            ).ratio()

            if best_match is None or similarity > best_match[0]:
                best_match = (similarity, candidate)

        similarity, best_candidate = best_match  # pyright: ignore[reportGeneralTypeIssues]

        if similarity < MATCH_SIMILARITY_THRESHOLD:
            continue

        unmatched_dir1.discard(path_in_dir1)
        unmatched_dir2.discard(best_candidate)

        changed = diff_texts(file1_lines, read_file_from_dir2(best_candidate))

        if changed > 0:
            changes.append(FileChange(path=path_in_dir1, changed=changed, path_new=best_candidate))

    return changes, sorted(unmatched_dir1), sorted(unmatched_dir2), equals


def format_path_rename_git_style(path_a: Path, path_b: Path | None) -> str:
    """
    Format a path rename in a style close to Git diff/commit summaries.
    Examples:
        scripts/__Packages/StashManager/{old.pcode => new.pcode}
        scripts/__Packages/{StashManager => StashItemRenderer}/my_block.pcode
        scripts/toto/nioup.txt => ernest/acab.txt
    """
    if path_b is None or path_a == path_b:
        return path_a.as_posix()

    a_parts = list(path_a.parts)
    b_parts = list(path_b.parts)

    prefix_parts = []
    suffix_parts = []

    for part1, part2 in list(zip(a_parts, b_parts)):
        if part1 != part2:
            break
        prefix_parts.append(part1)
        a_parts.pop(0)
        b_parts.pop(0)

    # If exactly one path side became empty after prefix scanning,
    # we move one segment/part back into the "rename" chunk.
    # This enables `foo/{bar => bar/baz}` instead of `foo/bar/{ => baz}`, like Git does.
    if prefix_parts and (not a_parts) != (not b_parts):
        part = prefix_parts.pop()
        a_parts.insert(0, part)
        b_parts.insert(0, part)

    for part1, part2 in zip(reversed(a_parts), reversed(b_parts)):
        if part1 != part2:
            break
        suffix_parts.append(part1)
        a_parts.pop()
        b_parts.pop()

    # If exactly one path side became empty after suffix scanning,
    # we move one segment/part back into the "rename" chunk.
    # This enables `{foo/bar => bar}/baz` instead of `{foo => }/bar/baz`, like Git does.
    if suffix_parts and (not a_parts) != (not b_parts):
        part = suffix_parts.pop()
        a_parts.append(part)
        b_parts.append(part)

    if not bool(prefix_parts or suffix_parts):
        # When there is no common prefix or suffix, drop the curly braces.
        return f"{path_a.as_posix()} => {path_b.as_posix()}"

    return (
        "/".join(prefix_parts)
        + ("/" if prefix_parts else "")
        + "{"
        + "/".join(a_parts)
        + " => "
        + "/".join(b_parts)
        + "}"
        + ("/" if suffix_parts else "")
        + "/".join(reversed(suffix_parts))
    )
