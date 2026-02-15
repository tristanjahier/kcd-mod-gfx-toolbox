from textwrap import dedent
from pathlib import Path

_PROJECT_ROOT_PATH: Path | None = None


def sample_text(text: str) -> str:
    """
    De-indent a multiline string, and strip leading and trailing blank lines.
    """
    return dedent(text).strip()


def sample_text_lines(text: str) -> list[str]:
    """
    De-indent a multiline string, and strip leading and trailing blank lines.
    Return a list of resulting lines.
    """
    return sample_text(text).splitlines()


def get_test_data_dir() -> Path:
    if _PROJECT_ROOT_PATH is None:
        raise RuntimeError("Project root path is undefined in tests helpers module.")

    return _PROJECT_ROOT_PATH / "tests/data/"


def read_data_file(rel_path: str) -> str:
    return (get_test_data_dir() / rel_path).read_text(encoding="utf-8")


def list_data_files(rel_path: str) -> list[Path]:
    files = [p for p in Path(get_test_data_dir() / rel_path).iterdir() if p.is_file()]
    files.sort(key=lambda p: p.name)
    return files
