import re
import shutil
import hashlib
from pathlib import Path
import tempfile
from rich.console import Console
from rich.markup import escape


"""Shared instance of Rich console."""
console = Console()

"""Shared instance of Rich console that outputs to stderr."""
stderr_console = Console(stderr=True)


def print_error(message: str | BaseException):
    """
    Print an error message (or exception) in the console.
    """
    if isinstance(message, BaseException):
        message = escape(str(message))

    stderr_console.print(f"ERROR: {message}", style="bold red", highlight=False)


def print_warning(message: str | BaseException):
    """
    Print a warning message (or exception) in the console.
    """
    if isinstance(message, BaseException):
        message = escape(str(message))

    stderr_console.print(f"WARNING: {message}", style="bold yellow", highlight=False)


def list_tree_files(path: Path, glob: str | None = None) -> set[Path]:
    """
    Return a set of all file paths in a directory subtree, relative to the root.
    """
    if glob is None:
        glob = "**/*"

    return {p.relative_to(path) for p in path.glob(glob) if p.is_file()}


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
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return None if set(name) == {"_"} else name


def get_temp_dir() -> Path:
    """
    Get a path to a directory named after the project inside the system's temporary directory.
    """
    return Path(tempfile.gettempdir()) / "kcd-mod-gfx-toolbox"
