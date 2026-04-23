"""Generic text and file diff primitives, with no knowledge of GFx."""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
import difflib
from pathlib import Path
from typing import Literal, NamedTuple, Self
import itertools
from kcd_gfx_toolbox.utils import list_tree_files, read_file_lines, sha256_file


class TextDiffSpan(NamedTuple):
    a: tuple[int, int]
    b: tuple[int, int]


@dataclass(frozen=True)
class TextDiff:
    spans: list[TextDiffSpan]
    lines_changed: int


@dataclass(frozen=True)
class FileDiff:
    """
    A small container object for file changes.
    """

    path: Path
    lines_changed: int
    spans: list[TextDiffSpan] = field(default_factory=list, hash=False)
    path_new: Path | None = None


def diff_file_trees_basic(dir1: Path, dir2: Path, glob: str | None = None) -> tuple[list[Path], list[Path], list[Path]]:
    """
    Perform a basic diff between two directories and their subtrees.
    Return a tuple of:
        1. file paths in common but with different contents
        2. file paths only present in directory 1
        3. file paths only present in directory 2
    """
    dir1_files = list_tree_files(dir1, glob)
    dir2_files = list_tree_files(dir2, glob)

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


def diff_texts(text1_lines: list[str], text2_lines: list[str]) -> TextDiff:
    """
    Compare two sets of text lines.
    Return number of touched lines (inserted, deleted or replaced),
    counting replacements as max(old_span, new_span).
    """
    seqmatch = difflib.SequenceMatcher(None, text1_lines, text2_lines, autojunk=False)
    diff_spans: list[TextDiffSpan] = []
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

        diff_spans.append(TextDiffSpan((i1, i2), (j1, j2)))

    return TextDiff(spans=diff_spans, lines_changed=changed)


def diff_file_trees(
    dir1: Path, dir2: Path, include_paths: set[Path] | None = None, glob: str | None = None
) -> tuple[list[FileDiff], list[Path], list[Path], list[Path]]:
    """
    Perform a diff between two directories and their subtrees.
    Return a tuple of:
        1. file change stats for common file paths and paired moved/renamed paths
        2. file paths only present in directory 1
        3. file paths only present in directory 2
        4. equal files (same path, same content)
    """
    dir1_files = list_tree_files(dir1, glob)
    dir2_files = list_tree_files(dir2, glob)

    if include_paths:

        def keep_path(p: Path) -> bool:
            return any(p.is_relative_to(path) for path in include_paths)

        dir1_files = {p for p in dir1_files if keep_path(p)}
        dir2_files = {p for p in dir2_files if keep_path(p)}

    common = sorted(dir1_files & dir2_files)

    changes: list[FileDiff] = []

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
        text_diff = diff_texts(file1_lines, file2_lines)

        if text_diff.lines_changed > 0:
            changes.append(FileDiff(path=rel_path, lines_changed=text_diff.lines_changed, spans=text_diff.spans))
        else:
            equals.append(rel_path)

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

        # Note: the following pairing logic is simplistic: just discard the same
        # number of hash-identical files on each side. It does not try to capture rename "intent".
        paired_count = min(len(paths_in_dir1), len(paths_in_dir2))
        paired_exact_matches = list(zip(paths_in_dir1[:paired_count], paths_in_dir2[:paired_count]))

        for p1, p2 in paired_exact_matches:
            unmatched_dir1.discard(p1)
            unmatched_dir2.discard(p2)

            # Pure rename change.
            changes.append(FileDiff(path=p1, path_new=p2, lines_changed=0))

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

        text_diff = diff_texts(file1_lines, read_file_from_dir2(best_candidate))

        changes.append(
            FileDiff(
                path=path_in_dir1, path_new=best_candidate, lines_changed=text_diff.lines_changed, spans=text_diff.spans
            )
        )

    return changes, sorted(unmatched_dir1), sorted(unmatched_dir2), equals


def unified_diff(lines_1: list[str], lines_2: list[str]) -> Iterator[str]:
    """Compare two sets of text lines and return the unified diff hunk lines."""
    return difflib.unified_diff(lines_1, lines_2)


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


@dataclass(frozen=True, slots=True)
class TextHunkLine:
    """
    A line in a text hunk identified by its source line number (0-based).
    It can be annotated with diff contextual information.
    """

    index: int
    text: str
    is_context: bool = False
    is_deletion: bool = False
    is_addition: bool = False

    def __post_init__(self) -> None:
        if sum((self.is_context, self.is_deletion, self.is_addition)) > 1:
            raise ValueError("A TextHunkLine can only have one annotation among context, deletion, or addition.")

    def reannotate(self, is_context: bool = False, is_deletion: bool = False, is_addition: bool = False) -> Self:
        return replace(self, is_context=is_context, is_deletion=is_deletion, is_addition=is_addition)

    def debug_repr(self, line_padding: int = 0) -> str:
        annotation = "ctx" if self.is_context else "del" if self.is_deletion else "add" if self.is_addition else "..."
        return f"({annotation}) {self.index:>{line_padding}d}:  {self.text}"

    def __repr__(self) -> str:
        return self.debug_repr()


class TextHunk(list[TextHunkLine]):
    """An ordered sequence of TextHunkLine representing a contiguous hunk of text."""

    def to_str_list(self) -> list[str]:
        return [ln.text for ln in self]

    def __repr__(self) -> str:
        line_padding = max((len(str(line.index)) for line in self), default=0)
        return "\n".join(ln.debug_repr(line_padding) for ln in self)


class DiffHunk(list[TextHunk]):
    """
    A sequence of TextHunk in the context of a diff, typically alternating between context and differing regions.
    """

    def lines(self) -> list[TextHunkLine]:
        return list(itertools.chain.from_iterable(self))

    @classmethod
    def wrap(cls, text_hunk: TextHunk) -> Self:
        return cls([text_hunk])


def cut_text_hunks_with_context(
    text_lines: list[str], selection: list[int] | set[int], context_length=3, merge: bool = False
) -> list[TextHunk]:
    """
    Extract text hunks (groups of consecutive lines) around a subselection of line indices.
    Capture up to `context_length` lines of context before and after the selected lines.
    If `merge` is True, adjacent or overlapping hunks are merged.
    """
    hunks: list[TextHunk] = []

    if not selection:
        return hunks

    selection = sorted(selection)

    spans: list[slice] = []
    current_sequence: list[int] = []

    for selected_line in selection:
        if not current_sequence or current_sequence[-1] == (selected_line - 1):
            current_sequence.append(selected_line)
            continue

        spans.append(slice(current_sequence[0], current_sequence[-1] + 1))
        current_sequence = [selected_line]

    spans.append(slice(current_sequence[0], current_sequence[-1] + 1))

    for span in spans:
        if span.start < 0 or span.stop > len(text_lines):
            raise ValueError(f"Line selection contains an out-of-bounds span: [{span.start}:{span.stop}].")

        hunk: TextHunk = TextHunk()

        for i in range(span.start - context_length, span.start):
            if i >= 0:
                hunk.append(TextHunkLine(i, text_lines[i], is_context=True))

        for i, line in enumerate(text_lines[span], start=span.start):
            hunk.append(TextHunkLine(i, line, is_context=False))

        for i in range(span.stop, span.stop + context_length):
            if i < len(text_lines):
                hunk.append(TextHunkLine(i, text_lines[i], is_context=True))

        hunks.append(hunk)

    hunks.sort(key=lambda h: h[0].index)  # Sort hunks by first line number.

    # Merge touching/overlapping hunks if required.
    if not merge or len(hunks) < 2:
        return hunks

    merged_hunks = []
    last_hunk = None

    for hunk in hunks:
        if last_hunk is None:
            last_hunk = hunk
            continue

        hunk_first_line = hunk[0].index
        last_hunk_last_line = last_hunk[-1].index

        if last_hunk_last_line >= hunk_first_line:
            last_hunk.extend(hunk)
            deduped_hunk: dict[int, TextHunkLine] = {}

            for line in last_hunk:
                known_line = deduped_hunk.get(line.index)  # Last known line for that index.

                if known_line is None or (known_line.is_context and not line.is_context):
                    deduped_hunk[line.index] = line

            last_hunk = TextHunk(deduped_hunk.values())

        else:
            merged_hunks.append(last_hunk)
            last_hunk = hunk

    merged_hunks.append(last_hunk)

    return merged_hunks


def align_hunk_pair_edge_context(hunk_1: TextHunk, hunk_2: TextHunk) -> tuple[TextHunk, TextHunk]:
    """
    Trim leading and trailing context lines so their edge context matches.
    """
    if len(hunk_1) == 0 or len(hunk_2) == 0:
        return hunk_1, hunk_2

    def _get_context_region(hnk: TextHunk, edge: Literal["leading", "trailing"]) -> TextHunk:
        ctx: list[TextHunkLine] = []
        for ln in hnk if edge == "leading" else reversed(hnk):
            if not ln.is_context:
                break
            ctx.append(ln)
        return TextHunk(ctx if edge == "leading" else reversed(ctx))

    # Get the start indexes of the common leading context.
    leading_context_1: TextHunk = _get_context_region(hunk_1, "leading")
    leading_context_2: TextHunk = _get_context_region(hunk_2, "leading")

    assert len(leading_context_1) < len(hunk_1) and len(leading_context_2) < len(hunk_2), (
        "Hunks must contain at least one non-context line!"
    )

    a_first_index = hunk_1[0].index
    b_first_index = hunk_2[0].index

    for ln_1, ln_2 in zip(reversed(leading_context_1), reversed(leading_context_2)):
        if ln_1.text != ln_2.text:
            break
        a_first_index = ln_1.index
        b_first_index = ln_2.index

    # Get the end indexes of the common trailing context.
    trailing_context_1: TextHunk = _get_context_region(hunk_1, "trailing")
    trailing_context_2: TextHunk = _get_context_region(hunk_2, "trailing")
    a_last_index = hunk_1[-1].index
    b_last_index = hunk_2[-1].index

    for ln_1, ln_2 in zip(trailing_context_1, trailing_context_2):
        if ln_1.text != ln_2.text:
            break
        a_last_index = ln_1.index
        b_last_index = ln_2.index

    return (
        TextHunk([ln for ln in hunk_1 if a_first_index <= ln.index <= a_last_index]),
        TextHunk([ln for ln in hunk_2 if b_first_index <= ln.index <= b_last_index]),
    )


def align_hunk_pairs(hunks_1: list[TextHunk], hunks_2: list[TextHunk]) -> list[tuple[TextHunk, TextHunk]]:
    """
    Align two lists of text hunks by pairing similar hunks together. Order is preserved.
    Hunk pairs cannot cross — a hunk earlier in the list cannot be paired with a hunk later than one already paired.
    Unmatched hunks are paired with an empty hunk on the other side.
    """
    hunk_pairs: list[tuple[TextHunk, TextHunk]] = []

    seqmatch = difflib.SequenceMatcher(
        None,
        ["\n".join((line.text for line in h)) for h in hunks_1],
        ["\n".join((line.text for line in h)) for h in hunks_2],
        autojunk=False,
    )

    def _flatten_hunk_list(hunk_list: list[TextHunk]) -> TextHunk:
        return TextHunk(itertools.chain.from_iterable(hunk_list))

    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag == "equal":
            hunk_pairs.append((_flatten_hunk_list(hunks_1[i1:i2]), _flatten_hunk_list(hunks_2[j1:j2])))
        elif tag == "replace":
            hunk_pairs.append((_flatten_hunk_list(hunks_1[i1:i2]), _flatten_hunk_list(hunks_2[j1:j2])))
        elif tag == "insert":
            hunk_pairs.append((TextHunk(), _flatten_hunk_list(hunks_2[j1:j2])))
        elif tag == "delete":
            hunk_pairs.append((_flatten_hunk_list(hunks_1[i1:i2]), TextHunk()))

    return [align_hunk_pair_edge_context(h1, h2) for h1, h2 in hunk_pairs]


def hunks_are_equal(hunk_1: TextHunk | DiffHunk, hunk_2: TextHunk | DiffHunk) -> bool:
    """Compare two hunks and return True if their texts are equal, regardless of line numbers."""
    lines_1 = hunk_1.lines() if isinstance(hunk_1, DiffHunk) else hunk_1
    lines_2 = hunk_2.lines() if isinstance(hunk_2, DiffHunk) else hunk_2
    return [line.text for line in lines_1] == [line.text for line in lines_2]


def diff_text_hunks(hunk_1: TextHunk, hunk_2: TextHunk) -> tuple[DiffHunk, DiffHunk]:
    """
    Compare two text hunks and return a pair of annotated DiffHunk.

    Text hunks are partitioned into sequences of either equal lines or differing lines (diff spans).
    Equal lines are annotated with is_context=True.
    Differing lines are annotated with is_deletion=True on hunk_1 and is_addition=True on hunk_2.
    Context segments are strictly equal. Segments can be empty (for pure deletions or pure additions).
    This data structure helps displaying side-by-side diffs.
    """
    diffed_hunk_1 = DiffHunk()
    diffed_hunk_2 = DiffHunk()

    hunk_1_lines: list[str] = [line.text for line in hunk_1]
    hunk_2_lines: list[str] = [line.text for line in hunk_2]
    seqmatch = difflib.SequenceMatcher(None, hunk_1_lines, hunk_2_lines, autojunk=False)

    for tag, i1, i2, j1, j2 in seqmatch.get_opcodes():
        if tag == "equal":
            diffed_hunk_1.append(TextHunk([line.reannotate(is_context=True) for line in hunk_1[i1:i2]]))
            diffed_hunk_2.append(TextHunk([line.reannotate(is_context=True) for line in hunk_2[j1:j2]]))

        else:
            diffed_hunk_1.append(TextHunk([line.reannotate(is_deletion=True) for line in hunk_1[i1:i2]]))
            diffed_hunk_2.append(TextHunk([line.reannotate(is_addition=True) for line in hunk_2[j1:j2]]))

    return (diffed_hunk_1, diffed_hunk_2)
