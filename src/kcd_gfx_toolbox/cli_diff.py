#!/usr/bin/env python3

from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Callable, Iterable
import typer
from .cli_extract import extraction_cache_key, resolve_ffdec, extract_gfx_contents
from .lib.avm1_pcode_normalization import NormalizationStats, normalize_file
from .lib.diff import FileChange, diff_file_trees, diff_file_trees_basic
from .lib.util import AnsiColor, ensure_empty_dir, print_error, get_temp_dir
from pathlib import Path
import shutil
import subprocess
from rich.console import Console, RenderableType
from rich.table import Table
from rich import box


class GfxDiffSet:
    """
    Container for diff information across command steps.
    """

    def __init__(self):
        self.differing_scripts: set[Path] = set()
        self.unmatched_a_scripts: set[Path] = set()
        self.unmatched_b_scripts: set[Path] = set()
        self.differing_scripts_details: dict[Path, ScriptDiffSet] = {}

    def has_differing_scripts(self) -> bool:
        return bool(self.differing_scripts)

    def has_unmatched_scripts_on_side_a(self) -> bool:
        return bool(self.unmatched_a_scripts)

    def has_unmatched_scripts_on_side_b(self) -> bool:
        return bool(self.unmatched_b_scripts)

    def is_empty(self) -> bool:
        return (
            not self.has_differing_scripts()
            and not self.has_unmatched_scripts_on_side_a()
            and not self.has_unmatched_scripts_on_side_b()
        )

    def populate_script_details_from_file_tree_diff(
        self,
        changes: list[FileChange],
        only_in_tree_a: list[Path],
        only_in_tree_b: list[Path],
    ):
        def fail_if_unknown_script(script_path: Path):
            if script_path not in self.differing_scripts:
                raise ValueError(f"Script path '{script_path}' is unknown.")

        for fch in changes:
            script_path = fch.path.parent
            fail_if_unknown_script(script_path)
            self.differing_scripts_details.setdefault(script_path, ScriptDiffSet()).differing_blocks.add(
                # Convert FileChange to ScriptBlockChange
                ScriptBlockChange(
                    name=fch.path.stem,
                    changed=fch.changed,
                    name_new=fch.path_new.stem if fch.path_new else None,
                )
            )

        for path in only_in_tree_a:
            script_path = path.parent
            fail_if_unknown_script(script_path)
            self.differing_scripts_details.setdefault(script_path, ScriptDiffSet()).unmatched_a_blocks.add(path.stem)

        for path in only_in_tree_b:
            script_path = path.parent
            fail_if_unknown_script(script_path)
            self.differing_scripts_details.setdefault(script_path, ScriptDiffSet()).unmatched_b_blocks.add(path.stem)

    def get_scripts_with_block_changes(self) -> set[Path]:
        return {scr for scr, det in self.differing_scripts_details.items() if det.has_differing_blocks()}

    def get_scripts_with_unmatched_blocks_on_side_a(self) -> set[Path]:
        return {scr for scr, det in self.differing_scripts_details.items() if det.has_unmatched_blocks_on_side_a()}

    def get_scripts_with_unmatched_blocks_on_side_b(self) -> set[Path]:
        return {scr for scr, det in self.differing_scripts_details.items() if det.has_unmatched_blocks_on_side_b()}

    def get_scripts_with_unmatched_blocks(self) -> set[Path]:
        return self.get_scripts_with_unmatched_blocks_on_side_a() | self.get_scripts_with_unmatched_blocks_on_side_b()

    def __rich_repr__(self):
        yield from self.__dict__.items()


class ScriptDiffSet:
    """
    Block-level diff details for one script path.

    It tracks changed blocks and blocks that exist only on side A or side B.
    """

    def __init__(self):
        self.differing_blocks: set[ScriptBlockChange] = set()
        self.unmatched_a_blocks: set[str] = set()
        self.unmatched_b_blocks: set[str] = set()

    def has_differing_blocks(self) -> bool:
        return bool(self.differing_blocks)

    def has_unmatched_blocks_on_side_a(self) -> bool:
        return bool(self.unmatched_a_blocks)

    def has_unmatched_blocks_on_side_b(self) -> bool:
        return bool(self.unmatched_b_blocks)

    def is_empty(self) -> bool:
        return (
            not self.has_differing_blocks()
            and not self.has_unmatched_blocks_on_side_a()
            and not self.has_unmatched_blocks_on_side_b()
        )

    def __rich_repr__(self):
        yield from self.__dict__.items()


@dataclass(frozen=True)
class ScriptBlockChange:
    """
    One changed block entry within a script.

    `name` is the block name on side A (or common name), `changed` is the
    touched-line count, and `name_new` is the paired name on side B when a
    rename pairing is detected.
    """

    name: str
    changed: int
    name_new: str | None = None


def build_script_path_tree_rows(script_paths: set[Path]) -> list[tuple[str, Path | None, str]]:
    """
    Render script paths as a directory/file tree.
    Return tuples:
        1. rendered tree row
        2. matched script path for this row, or None for intermediate nodes
        3. prefix to use for children rows under this node
    """
    tree: dict[str, dict] = {}
    segments_to_script: dict[tuple[str, ...], Path] = {}

    for p in script_paths:
        segments = p.parts

        # Build a lookup table for later.
        segments_to_script[segments] = p

        # Create the tree structure as a dict, where keys are path segments.
        node = tree
        for segment in segments:
            node = node.setdefault(segment, {})

    def render_tree_node(
        tree_node: dict[str, dict],
        prefix: str = "",
        path_prefix_segments: tuple[str, ...] = (),
    ) -> list[tuple[str, Path | None, str]]:
        rows: list[tuple[str, Path | None, str]] = []
        children = sorted(tree_node.keys())  # sort paths in alphabetical order.

        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            path_segments = (*path_prefix_segments, child)
            leaf_script = segments_to_script.get(path_segments)

            if leaf_script is None:
                child_text = f"{child}/"
            else:
                child_text = f"[bold cyan]{child}[/bold cyan]"

            if not path_prefix_segments:
                # Roots do not need a tree connector character.
                row_text = child_text
                child_prefix = "    "
            else:
                connector = "└── " if is_last else "├── "
                row_text = f"{prefix}{connector}{child_text}"
                child_prefix = prefix + ("    " if is_last else "│   ")

            rows.append((row_text, leaf_script, child_prefix))

            # Recursively render all tree nodes, depth-first.
            rows.extend(render_tree_node(tree_node[child], child_prefix, path_segments))

        return rows

    return render_tree_node(tree)


def unfold_script_tree_in_table(
    script_paths: set[Path],
    table: Table,
    get_block_rows: Callable[[Path], Iterable[tuple[RenderableType | None, ...]]],
) -> None:
    """
    Append script paths and blocks as a tree to a Rich table.
    Script paths are sorted in alphabetical order.
    Append block rows to each leaf script using `get_block_rows`.
    """
    tree_rows = build_script_path_tree_rows(script_paths)

    for row_text, script_path, leaf_prefix in tree_rows:
        table.add_row(row_text, "", "")

        if script_path is None:
            continue  # continue unfolding the tree until we reached a script

        for block_text, *block_attr in get_block_rows(script_path):
            block_text = f"{leaf_prefix}[bright_yellow]◈[/bright_yellow] {block_text}"
            table.add_row(block_text, *block_attr)


def command(
    file_a: Annotated[Path, typer.Argument(help="The left (A) file of the comparison.")],
    file_b: Annotated[Path, typer.Argument(help="The right (B) file of the comparison.")],
    ffdec_path: Annotated[
        Path | None,
        typer.Option("--ffdec", help="Path to the ffdec binary. Only required if it is not in the system PATH."),
    ] = None,
    use_extraction_cache: Annotated[
        bool,
        typer.Option(
            "--cache-extraction/--no-extraction-cache",
            help="Use extraction cache (default). Disable to force re-extraction.",
        ),
    ] = True,
):
    """
    Compare scripts between two GFx files to surface meaningful changes through normalization.
    """
    console = Console()

    # ================================================================
    # Sanity checks

    file_a = file_a.resolve()
    file_b = file_b.resolve()

    if not file_a.is_file():
        print_error(f"Invalid input: {file_a} is not a file.")
        raise typer.Exit(code=1)

    if not file_b.is_file():
        print_error(f"Invalid input: {file_b} is not a file.")
        raise typer.Exit(code=1)

    temp_dir = get_temp_dir()

    if temp_dir.exists() and not temp_dir.is_dir():
        print_error(f"Temp path exists but is not a directory: {temp_dir}")
        raise typer.Exit(code=1)

    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        ffdec_path = resolve_ffdec(ffdec_path)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    print(f"{AnsiColor.LIGHT_YELLOW}File A:{AnsiColor.RESET} {file_a}")
    print(f"{AnsiColor.LIGHT_YELLOW}File B:{AnsiColor.RESET} {file_b}")
    print(
        f"{AnsiColor.LIGHT_YELLOW}Temp dir:{AnsiColor.RESET} \033]8;;{temp_dir.as_uri()}\033\\{temp_dir}\033]8;;\033\\"
    )
    print(f"{AnsiColor.LIGHT_YELLOW}Using ffdec:{AnsiColor.RESET} {ffdec_path}")

    # Create an object to carry the diff information across steps, updated progressively.
    diffset = GfxDiffSet()

    # ================================================================
    # Step 1: extract contents from both files.
    # For that we use "JPEXS Free Flash Decompiler" aka ffdec.

    print(f"\n{AnsiColor.BLUE}» 1: Extraction of GFX scripts as p-code{AnsiColor.RESET}\n")

    # Extraction of file A.
    file_a_path_hash = extraction_cache_key(file_a)
    extraction_dir_a = (temp_dir / f"{file_a.stem}_{file_a_path_hash}" / "raw").resolve()
    print(f"{file_a} -> {extraction_dir_a}")

    if not use_extraction_cache or not extraction_dir_a.is_dir():
        try:
            shutil.rmtree(extraction_dir_a)
        except FileNotFoundError:
            pass

        extraction_dir_a.mkdir(parents=True, exist_ok=True)

        try:
            extract_gfx_contents(ffdec_path, file_a, extraction_dir_a)
        except subprocess.CalledProcessError as e:
            print_error(f"ffdec failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            raise typer.Exit(code=1)
    else:
        print("Extraction directory already exists. Reusing.")

    # Extraction of file B.
    file_b_path_hash = extraction_cache_key(file_b)
    extraction_dir_b = (temp_dir / f"{file_b.stem}_{file_b_path_hash}" / "raw").resolve()
    print(f"{file_b} -> {extraction_dir_b}")

    if not use_extraction_cache or not extraction_dir_b.is_dir():
        try:
            shutil.rmtree(extraction_dir_b)
        except FileNotFoundError:
            pass

        extraction_dir_b.mkdir(parents=True, exist_ok=True)

        try:
            extract_gfx_contents(ffdec_path, file_b, extraction_dir_b)
        except subprocess.CalledProcessError as e:
            print_error(f"ffdec failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            raise typer.Exit(code=1)
    else:
        print("Extraction directory already exists. Reusing.")

    # ================================================================
    # Step 2: perform a naive diff between the two directory trees.

    print(f"\n{AnsiColor.BLUE}» 2: Searching for file differences{AnsiColor.RESET}\n")

    different, only_in_a, only_in_b = diff_file_trees_basic(extraction_dir_a, extraction_dir_b)

    # Strip ".pcode" extension as we want to reflect the inner GFx structure, not the extraction dir.
    diffset.differing_scripts = {p.with_suffix("") for p in different}
    diffset.unmatched_a_scripts = {p.with_suffix("") for p in only_in_a}
    diffset.unmatched_b_scripts = {p.with_suffix("") for p in only_in_b}

    if diffset.is_empty():
        print(f"{AnsiColor.GREEN}Both files are identical.{AnsiColor.RESET}")
        return

    if diffset.has_unmatched_scripts_on_side_a():
        print(f"Scripts only present in {file_a}:")
        for path in sorted(diffset.unmatched_a_scripts):
            print(f"{path}")
        print()

    if diffset.has_unmatched_scripts_on_side_b():
        print(f"Scripts only present in {file_b}:")
        for path in sorted(diffset.unmatched_b_scripts):
            print(f"{path}")
        print()

    if diffset.has_differing_scripts():
        print("Common scripts that differ:")
        for path in sorted(diffset.differing_scripts):
            print(f"{path}")
    else:
        console.print("[yellow]Common scripts are identical. Comparing unmatched scripts is not supported.[/yellow]")
        return

    # ================================================================
    # Step 3: normalize the differing scripts, to remove the noise in p-codes due to decompilation,
    # and to highlight the real logical differences. The normalization is done at a "block level".
    # Files are split into blocks (top level scope, functions).

    normalization_dir_a = (temp_dir / f"{file_a.stem}_{file_a_path_hash}" / "normalized").resolve()
    normalization_dir_b = (temp_dir / f"{file_b.stem}_{file_b_path_hash}" / "normalized").resolve()

    normalization_dir_a.mkdir(parents=True, exist_ok=True)
    normalization_dir_b.mkdir(parents=True, exist_ok=True)

    print(f"\n{AnsiColor.BLUE}» 3: Normalizing differing scripts into p-code blocks{AnsiColor.RESET}\n")

    normalization_results_a: list[tuple[Path, NormalizationStats]] = []
    normalization_results_b: list[tuple[Path, NormalizationStats]] = []

    for script_path in diffset.differing_scripts:
        src_a = (extraction_dir_a / script_path).with_suffix(".pcode")
        src_b = (extraction_dir_b / script_path).with_suffix(".pcode")

        # Preserve tree structure and transform file "XXXX.pcode" into directory "XXXX/".
        normalized_blocks_dir_a = normalization_dir_a / script_path
        normalized_blocks_dir_b = normalization_dir_b / script_path

        ensure_empty_dir(normalized_blocks_dir_a)

        try:
            norm_stats_a = normalize_file(src_a, normalized_blocks_dir_a)
            normalization_results_a.append((script_path, norm_stats_a))
        except Exception as e:
            print_error(f"Normalization failed: {src_a}")
            print_error(e)
            raise typer.Exit(code=1)

        ensure_empty_dir(normalized_blocks_dir_b)

        try:
            norm_stats_b = normalize_file(src_b, normalized_blocks_dir_b)
            normalization_results_b.append((script_path, norm_stats_b))
        except Exception as e:
            print_error(f"Normalization failed: {src_b}")
            print_error(e)
            raise typer.Exit(code=1)

    print(f"{file_a}:")

    norm_table1 = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    norm_table1.add_column("p-code file")
    norm_table1.add_column("Blocks", justify="right")
    norm_table1.add_column("Named", justify="right")
    norm_table1.add_column("Anonymous", justify="right")
    norm_table1.add_column("Top-level", justify="right")

    for rel_path, stats in normalization_results_a:
        norm_table1.add_row(
            str(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console.print(norm_table1)

    print(f"\n{file_b}:")

    norm_table2 = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    norm_table2.add_column("p-code file")
    norm_table2.add_column("Blocks", justify="right")
    norm_table2.add_column("Named", justify="right")
    norm_table2.add_column("Anonymous", justify="right")
    norm_table2.add_column("Top-level", justify="right")

    for rel_path, stats in normalization_results_b:
        norm_table2.add_row(
            str(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console.print(norm_table2)

    # ================================================================
    # Step 4: compare normalized p-code blocks to spot the real differences.

    print(f"\n{AnsiColor.BLUE}» 4: Comparison of normalized code{AnsiColor.RESET}\n")

    changes, only_in_a, only_in_b = diff_file_trees(
        normalization_dir_a, normalization_dir_b, include_paths=diffset.differing_scripts
    )

    if not changes and not only_in_a and not only_in_b:
        print(
            f"{AnsiColor.GREEN}Normalized trees are identical. The difference might be decompilation noise only.{AnsiColor.RESET}"
        )
        return

    # Organize file tree diffs by script origin.
    diffset.populate_script_details_from_file_tree_diff(changes, only_in_a, only_in_b)

    changed_count = len(changes)
    deleted_count = len(only_in_a)
    created_count = len(only_in_b)
    changed_lines_total = sum(ch.changed for ch in changes)

    console.print(
        f"Summary: "
        f"[yellow]{changed_count} modified[/yellow], "
        f"[red]{deleted_count} deleted[/red], "
        f"[green]{created_count} created[/green] "
        f"({changed_lines_total} changed lines)\n"
    )

    diff_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, header_style=None)
    diff_table.add_column("Script block relative path")
    diff_table.add_column("State")
    diff_table.add_column("Lines changed", justify="right")

    if changes:
        diff_table.add_section()

        def _get_modified_block_rows(script: Path):
            block_change_rows: list[tuple[str, int]] = []

            for ch in diffset.differing_scripts_details[script].differing_blocks:
                display_text = f"{ch.name} [bright_yellow]=>[/bright_yellow] {ch.name_new}" if ch.name_new else ch.name
                block_change_rows.append((display_text, ch.changed))

            # Sort by largest changes first, then by name.
            block_change_rows.sort(key=lambda row: (-row[1], row[0]))

            for display_text, changed in block_change_rows:
                yield (display_text, "[italic yellow]modified[/italic yellow]", str(changed))

        unfold_script_tree_in_table(diffset.get_scripts_with_block_changes(), diff_table, _get_modified_block_rows)

    if only_in_a or only_in_b:
        diff_table.add_section()

        def _get_unmatched_block_rows(script: Path):
            unmatched_block_rows = []

            for path in diffset.differing_scripts_details[script].unmatched_a_blocks:
                unmatched_block_rows.append((path, "[italic red]deleted[/italic red]", "-"))

            for path in diffset.differing_scripts_details[script].unmatched_b_blocks:
                unmatched_block_rows.append((path, "[italic green]created[/italic green]", "-"))

            # Sort by block name.
            return sorted(unmatched_block_rows, key=lambda row: row[0])

        unfold_script_tree_in_table(diffset.get_scripts_with_unmatched_blocks(), diff_table, _get_unmatched_block_rows)

    console.print(diff_table)
