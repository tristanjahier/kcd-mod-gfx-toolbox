#!/usr/bin/env python3

from .extract import extraction_cache_key, resolve_ffdec, extract_gfx_contents
from .lib.avm1_pcode_normalization import NormalizationStats, normalize_file
from .lib.diff import diff_file_trees, diff_file_trees_basic
from .lib.util import AnsiColor, ensure_empty_dir, print_error, get_temp_dir
from pathlib import Path
import argparse
import shutil
import subprocess
from rich.console import Console
from rich.table import Table
from rich import box


def read_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("file_a", type=Path)
    argument_parser.add_argument("file_b", type=Path)
    argument_parser.add_argument("--ffdec", type=Path)
    argument_parser.add_argument(
        "--cache-extraction",
        dest="use_extraction_cache",
        action="store_true",
        help="Use extraction cache (default).",
    )
    argument_parser.add_argument(
        "--no-extraction-cache",
        dest="use_extraction_cache",
        action="store_false",
        help="Disable extraction cache and force re-extraction.",
    )
    argument_parser.set_defaults(use_extraction_cache=True)
    return argument_parser.parse_args()


def main() -> int:
    args = read_arguments()

    # ================================================================
    # Sanity checks

    file_a = args.file_a.resolve()
    file_b = args.file_b.resolve()

    if not file_a.is_file():
        print_error(f"Invalid input: {file_a} is not a file.")
        return 1

    if not file_b.is_file():
        print_error(f"Invalid input: {file_b} is not a file.")
        return 1

    temp_dir = get_temp_dir()

    if temp_dir.exists() and not temp_dir.is_dir():
        print_error(f"Temp path exists but is not a directory: {temp_dir}")
        return 1

    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        ffdec_path = resolve_ffdec(args.ffdec)
    except FileNotFoundError as e:
        print_error(e)
        return 1

    print(f"{AnsiColor.LIGHT_YELLOW}File A:{AnsiColor.RESET} {file_a}")
    print(f"{AnsiColor.LIGHT_YELLOW}File B:{AnsiColor.RESET} {file_b}")
    print(
        f"{AnsiColor.LIGHT_YELLOW}Temp dir:{AnsiColor.RESET} \033]8;;{temp_dir.as_uri()}\033\\{temp_dir}\033]8;;\033\\"
    )
    print(f"{AnsiColor.LIGHT_YELLOW}Using ffdec:{AnsiColor.RESET} {ffdec_path}")

    console = Console()

    # ================================================================
    # Step 1: extract contents from both files.
    # For that we use "JPEXS Free Flash Decompiler" aka ffdec.

    use_extraction_cache: bool = args.use_extraction_cache

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
            print_error(f"ffdec-cli.exe failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            return 1
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
            print_error(f"ffdec-cli.exe failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            return 1
    else:
        print("Extraction directory already exists. Reusing.")

    # ================================================================
    # Step 2: perform a naive diff between the two directory trees.

    print(f"\n{AnsiColor.BLUE}» 2: Searching for file differences{AnsiColor.RESET}\n")

    only_in_a, only_in_b, different = diff_file_trees_basic(extraction_dir_a, extraction_dir_b)

    if only_in_a:
        print(f"Scripts only present in {file_a}:")
        for path in only_in_a:
            print(f"{path}")
        print()

    if only_in_b:
        print(f"Scripts only present in {file_b}:")
        for path in only_in_b:
            print(f"{path}")
        print()

    if different:
        print("Common scripts that differ:")
        for path in different:
            print(f"{path}")

    if not different and not only_in_a and not only_in_b:
        print(f"{AnsiColor.GREEN}Both files are identical.{AnsiColor.RESET}")
        return 0
    elif not different:
        print(f"{AnsiColor.YELLOW}Common scripts are identical. Comparing the rest is not supported.{AnsiColor.RESET}")
        return 0

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
    normalized_paths: list[Path] = []

    for rel_path in different:
        src_a = extraction_dir_a / rel_path  # script path inside file A
        src_b = extraction_dir_b / rel_path  # script path inside file B

        # Preserve tree structure and transform file "XXXX.pcode" into directory "XXXX/".
        normalized_blocks_dir_a = (normalization_dir_a / rel_path).with_suffix("")
        normalized_blocks_dir_b = (normalization_dir_b / rel_path).with_suffix("")
        normalized_paths.append(rel_path.with_suffix(""))

        ensure_empty_dir(normalized_blocks_dir_a)

        try:
            norm_stats_a = normalize_file(src_a, normalized_blocks_dir_a)
            normalization_results_a.append((rel_path, norm_stats_a))
        except Exception as e:
            print_error(f"Normalization failed: {src_a}")
            print_error(e)
            return 1

        ensure_empty_dir(normalized_blocks_dir_b)

        try:
            norm_stats_b = normalize_file(src_b, normalized_blocks_dir_b)
            normalization_results_b.append((rel_path, norm_stats_b))
        except Exception as e:
            print_error(f"Normalization failed: {src_b}")
            print_error(e)
            return 1

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

    only_in_a, only_in_b, changes = diff_file_trees(
        normalization_dir_a, normalization_dir_b, include_paths=normalized_paths
    )

    if not changes and not only_in_a and not only_in_b:
        print(
            f"{AnsiColor.GREEN}Normalized trees are identical. The difference might be decompilation noise only.{AnsiColor.RESET}"
        )
        return 0

    if only_in_a:
        print(f"Normalized blocks only present in {file_a}:")
        for path in only_in_a:
            print(f"{path}")

    if only_in_b:
        print(f"Normalized blocks only present in {file_b}:")
        for path in only_in_b:
            print(f"{path}")

    if changes:
        # Show largest changes first.
        changes.sort(key=lambda c: c.changed, reverse=True)
        print("Normalized blocks that differ:")

        diff_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, header_style=None)
        diff_table.add_column("Relative inner path")
        diff_table.add_column("Lines changed", justify="right")
        for ch in changes:
            diff_table.add_row(str(ch.path), str(ch.changed))

        console.print(diff_table)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
