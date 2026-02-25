#!/usr/bin/env python3

from pathlib import Path
import platform
import shutil
import subprocess
from typing import Annotated
import typer
from .lib.util import AnsiColor, ensure_empty_dir, get_temp_dir, print_error, sha256_str


def resolve_ffdec(arg: Path | None) -> Path:
    ffdec_path = arg

    if ffdec_path is None:
        # If nothing was provided as an argument, we try to auto-discover it (via PATH).
        if platform.system().lower() == "windows":
            found_path = shutil.which("ffdec-cli") or shutil.which("ffdec-cli.exe")
        else:
            found_path = shutil.which("ffdec") or shutil.which("ffdec.sh")
        if found_path:
            return Path(found_path)
        raise FileNotFoundError("Unable to automatically resolve the path to ffdec.")
    else:
        # If a path was provided, we just need to validate it.
        ffdec_path = ffdec_path.resolve()
        if not ffdec_path.is_file():
            raise FileNotFoundError(f"The provided ffdec binary path ({ffdec_path}) does not exist or is not a file.")

    return ffdec_path


def extraction_cache_key(path: Path) -> str:
    st = path.stat()
    sig = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return sha256_str(sig)


def extract_gfx_contents(ffdec_bin_path: Path, file_path: Path, output_dir: Path):
    return subprocess.run(
        [str(ffdec_bin_path), "-format", "script:pcode", "-export", "script", str(output_dir), str(file_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


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
