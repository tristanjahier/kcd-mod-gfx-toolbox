import re
import shutil
import sys
import hashlib
from pathlib import Path
from enum import StrEnum


class AnsiColor(StrEnum):
    """
    A collection of ANSI escape codes used by CLI output formatting.
    """

    RED = "\x1b[91m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    LIGHT_YELLOW = "\x1b[93m"
    BLUE = "\x1b[36m"
    DIM = "\x1b[2m"
    RESET = "\x1b[0m"


def print_error(err: str | BaseException):
    """
    Print an error message (or exception) in the console.
    """
    print(f"{AnsiColor.RED}ERROR: {err}{AnsiColor.RESET}", file=sys.stderr)


def list_tree_files(path: Path) -> set[Path]:
    """
    Return a set of all file paths in a directory subtree, relative to the root.
    """
    return {p.relative_to(path) for p in path.rglob("*") if p.is_file()}


def sha256_file(path: Path) -> str:
    """
    Compute the SHA 256 digest of a file.
    """
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def sha256_str(s: str) -> str:
    """
    Compute the SHA 256 digest of a string.
    """
    return hashlib.sha256(bytes(s, "utf-8")).hexdigest()


def ensure_empty_dir(path: Path) -> None:
    """
    Ensure that the given path is an empty directory (destructive!).
    """
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        pass

    path.mkdir(parents=True, exist_ok=True)


def read_file_lines(file: Path) -> list[str]:
    """
    Read the file contents and split them into lines.
    """
    return file.read_text(encoding="utf-8", errors="replace").splitlines()


def safe_filename(name: str) -> str | None:
    """
    Ensure that the string contains only valid characters for file names.
    None if impossible.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip() or None
