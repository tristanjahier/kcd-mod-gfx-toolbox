from pathlib import Path
import platform
import shutil
import subprocess
from .utils import sha256_str


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
