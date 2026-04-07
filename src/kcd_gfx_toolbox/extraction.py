from pathlib import Path
import platform
import shutil
import subprocess


def resolve_ffdec(arg: Path | None) -> Path:
    ffdec_path = arg

    if ffdec_path is None:
        # If nothing was provided as an argument, we try to auto-discover it (via PATH or via platform defaults).
        found_path = None

        if platform.system().lower() == "windows":
            found_path = shutil.which("ffdec-cli") or shutil.which("ffdec-cli.exe")
        elif platform.system().lower() == "darwin":
            default_macos_path = "/Applications/FFDec.app/Contents/MacOS/FFDec"
            if Path(default_macos_path).is_file():
                found_path = default_macos_path

        if not found_path:
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


def extract_gfx_pcode(ffdec_bin_path: Path, file_path: Path, output_dir: Path):
    return subprocess.run(
        [str(ffdec_bin_path), "-format", "script:pcode", "-export", "script", str(output_dir), str(file_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def extract_gfx_actionscript(ffdec_bin_path: Path, file_path: Path, output_dir: Path):
    return subprocess.run(
        [str(ffdec_bin_path), "-format", "script:as", "-export", "script", str(output_dir), str(file_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def extract_gfx_debug_swd(ffdec_bin_path: Path, file_path: Path, output_dir: Path, pcode: bool):
    debug_file_name = f"debug_{'pcode' if pcode else 'actionscript'}"
    output_path = output_dir / debug_file_name

    result = subprocess.run(
        [
            str(ffdec_bin_path),
            "-enabledebugging",
            "-generateswd",
            *(["-pcode"] if pcode else []),
            str(file_path),
            str(output_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    # A .swd file has been created along with output_path. This is the target file.
    output_path.unlink()

    return result


def extract_gfx_contents(ffdec_bin_path: Path, file_path: Path, output_dir: Path):
    extract_gfx_pcode(ffdec_bin_path, file_path, output_dir)
    extract_gfx_actionscript(ffdec_bin_path, file_path, output_dir)
    extract_gfx_debug_swd(ffdec_bin_path, file_path, output_dir, pcode=True)
    extract_gfx_debug_swd(ffdec_bin_path, file_path, output_dir, pcode=False)
