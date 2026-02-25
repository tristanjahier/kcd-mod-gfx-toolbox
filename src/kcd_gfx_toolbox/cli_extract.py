#!/usr/bin/env python3

from pathlib import Path
import subprocess
from typing import Annotated
import typer
from .extraction import extract_gfx_contents, extraction_cache_key, resolve_ffdec
from .utils import AnsiColor, ensure_empty_dir, get_temp_dir, print_error


def command(
    input_file: Annotated[Path, typer.Argument(help="The GFx file to extract.")],
    ffdec_path: Annotated[
        Path | None,
        typer.Option("--ffdec", help="Path to the ffdec binary. Only required if it is not in the system PATH."),
    ] = None,
):
    """
    Extract scripts from a GFx file into a temporary directory.
    """
    input_file = input_file.resolve()

    if not input_file.is_file():
        print_error(f"Invalid input: {input_file} does not exist or is not a file.")
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

    print(f"Using ffdec at {ffdec_path}")

    input_file_hash = extraction_cache_key(input_file)
    output_dir = (temp_dir / f"{input_file.stem}_{input_file_hash}" / "raw").resolve()

    print(f"Extracting {input_file.name} contents in: {output_dir}")

    ensure_empty_dir(output_dir)

    try:
        extract_gfx_contents(ffdec_path, input_file, output_dir)
    except subprocess.CalledProcessError as e:
        print_error(f"ffdec failed with code {e.returncode}:")
        if e.stderr:
            print_error(e.stderr)
        raise typer.Exit(code=1)

    print(f"{AnsiColor.GREEN}Extraction complete.{AnsiColor.RESET}")
