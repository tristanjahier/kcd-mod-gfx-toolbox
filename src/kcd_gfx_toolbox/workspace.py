from pathlib import Path

from .utils import get_temp_dir, list_tree_files, sha256_str


def temp_workspace_name_for_file(path: Path) -> str:
    """Generate a stable file key used to automatically name a temporary workspace."""
    st = path.stat()
    sig = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return path.stem + "_" + sha256_str(sig)


class Workspace:
    """
    Represent the on-disk workspace for a GFx file.

    A workspace stores the intermediate artifacts used by extraction,
    normalization, sourcemap inspection, and diff rendering. It provides a
    single place to locate those files and validate whether a cached workspace
    is usable.
    """

    def __init__(self, base_path: Path):
        self._base_path = base_path.resolve()

    @property
    def base_path(self) -> Path:
        """Return the root directory of this workspace."""
        return self._base_path

    def extraction_dir(self) -> Path:
        """Return the directory that contains extracted GFx artifacts."""
        return self._base_path / "raw"

    def extraction_path(self, rel_path: Path | str) -> Path:
        """Return a path inside the extraction directory."""
        full_path = (self.extraction_dir() / Path(rel_path)).resolve()

        if not full_path.is_relative_to(self.extraction_dir()):
            raise ValueError("Extraction path must be relative to workspace.")

        return full_path

    def find_debug_pcode_swd_file(self) -> Path:
        """Return the SWD file for debugging extracted p-code scripts."""
        swd_file = self.extraction_path("debug_pcode.swd")

        if not swd_file.exists():
            raise FileNotFoundError(f"SWD debug file not found: {swd_file}.")

        return swd_file

    def find_debug_actionscript_swd_file(self) -> Path:
        """Return the SWD file for debugging extracted ActionScript scripts."""
        swd_file = self.extraction_path("debug_actionscript.swd")

        if not swd_file.exists():
            raise FileNotFoundError(f"SWD debug file not found: {swd_file}.")

        return swd_file

    def extraction_dir_has_content(self) -> bool:
        """
        Check whether the extraction directory exists and is not empty.
        """
        directory = self.extraction_dir()

        return directory.is_dir() and any(directory.iterdir())

    def extraction_dir_has_valid_contents(self) -> bool:
        """
        Check whether the extraction directory contains files that look like valid extracted GFx contents.

        Verifies the presence of expected files and directories, and that pcode and
        ActionScript files are paired. Does not validate file integrity because it is intended
        as a fast, cheap check for cached data.
        """
        directory = self.extraction_dir()

        if not directory.is_dir():
            return False

        try:
            self.find_debug_pcode_swd_file()
            self.find_debug_actionscript_swd_file()
        except FileNotFoundError:
            return False

        scripts_dir = directory / "scripts"

        if not scripts_dir.is_dir():
            return False

        pcode_files = list_tree_files(scripts_dir, "**/*.pcode")

        if not pcode_files:
            return False

        actionscript_files = list_tree_files(scripts_dir, "**/*.as")

        if not actionscript_files:
            return False

        if {f.with_suffix("") for f in pcode_files} != {f.with_suffix("") for f in actionscript_files}:
            return False

        return True

    def normalization_dir(self) -> Path:
        """Return the directory that contains normalized p-code artifacts."""
        return self._base_path / "normalized_scripts"

    def normalization_path(self, rel_path: Path | str) -> Path:
        """Return a path inside the normalization directory."""
        full_path = (self.normalization_dir() / Path(rel_path)).resolve()

        if not full_path.is_relative_to(self.normalization_dir()):
            raise ValueError("Normalization path must be relative to workspace.")

        return full_path

    def normalization_dir_has_content(self) -> bool:
        """
        Check whether the normalization directory exists and is not empty.
        """
        directory = self.normalization_dir()

        return directory.is_dir() and any(directory.iterdir())

    def script_normalization_dir_has_valid_contents(self, directory: Path) -> bool:
        """
        Check whether a script normalization directory contains valid normalized p-code blocks.

        Verifies the presence of expected files: source maps, order.txt.
        Does not validate file integrity because it is intended as a fast, cheap check for cached data.
        """
        block_order_file = directory / "order.txt"

        if not block_order_file.is_file():
            return False

        try:
            block_list = block_order_file.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, UnicodeDecodeError):
            return False

        block_names = {name for name in block_list if name.strip()}

        if not block_names:
            return False

        pcode_files = list_tree_files(directory, glob="*.pcode")

        if {f.stem for f in pcode_files} != block_names:
            return False

        sourcemap_files = list_tree_files(directory, glob="*.pcode.map")

        if {f.name for f in pcode_files} != {f.with_suffix("").name for f in sourcemap_files}:
            return False

        return True

    def normalization_dir_has_valid_contents(self) -> bool:
        """
        Check whether the normalization directory contains files that look like valid normalized p-code scripts.
        """
        directory = self.normalization_dir()

        if not directory.is_dir():
            return False

        empty = True

        for p in directory.rglob("*"):
            if not p.is_dir() or any(c.is_dir() for c in p.iterdir()):
                continue

            empty = False

            if not self.script_normalization_dir_has_valid_contents(p):
                return False

        return not empty

    def find_raw_pcode_file(self, script_path: Path | str) -> Path:
        """Return the path to a raw p-code file for an internal GFx script path."""
        file = self.extraction_path(Path("scripts") / script_path).with_suffix(".pcode")

        if not file.exists():
            raise FileNotFoundError(f"Script {script_path} not found in workspace at '{file}'.")

        return file

    def find_actionscript_file(self, script_path: Path | str) -> Path:
        """Return the path to a raw ActionScript file for an internal GFx script path."""
        file = self.extraction_path(Path("scripts") / script_path).with_suffix(".as")

        if not file.exists():
            raise FileNotFoundError(f"Script {script_path} not found in workspace at '{file}'.")

        return file

    def list_normalized_block_files(self, script_path: Path | str) -> set[Path]:
        """List the normalized block files for an internal GFx script path."""
        directory = self.normalization_path(script_path)

        if not directory.is_dir():
            raise FileNotFoundError(f"Normalized script block order file not found in workspace at '{directory}'.")

        return list_tree_files(directory, "*.pcode")

    def find_block_order_file(self, script_path: Path | str) -> Path:
        """Return the path to a normalized block order file for an internal GFx script path."""
        file = self.normalization_path(Path(script_path) / "order.txt")

        if not file.exists():
            raise FileNotFoundError(f"Normalized script block order file not found in workspace at '{file}'.")

        return file

    @classmethod
    def create_as_temporary_directory(cls, source_file: Path):
        """Create a workspace in a temporary directory, inferred from the source file's identity."""
        return cls((get_temp_dir() / temp_workspace_name_for_file(source_file)).resolve())
