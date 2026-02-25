#!/usr/bin/env python3

from pathlib import Path
from typing import Annotated
import typer
from .lib.avm1_pcode_normalization import normalize_file
from .lib.util import AnsiColor, print_error


def command(
    input_file: Annotated[Path, typer.Argument(help="The p-code file to normalize.")],
    output_dir: Annotated[Path, typer.Argument(help="The directory where to write normalized files.")],
):
    """
    Split a p-code file into logical blocks and normalize each of them.
    """
    input_file = input_file.resolve()

    if not input_file.is_file():
        print_error(f"Invalid input: {input_file} does not exist or is not a file.")
        raise typer.Exit(code=1)

    output_dir = output_dir.resolve()

    stats = normalize_file(input_file, output_dir)

    print(
        f"{input_file.name}: split into {stats.total_blocks} blocks",
        f"({stats.named_blocks} named, {stats.anonymous_blocks} anonymous, {stats.toplevel_blocks} top-level)",
    )

    print(f"{AnsiColor.GREEN}Normalization complete.{AnsiColor.RESET}")
