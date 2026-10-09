import argparse
import fnmatch
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "lambda-deployment.zip"

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "venv",
}
EXCLUDED_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.log",
    "*.pyc",
    "*.pyo",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.tmp",
    "*.temp",
    ".DS_Store",
)


def _should_exclude(
    path: Path,
    root: Path,
    output: Path,
    temporary_path: Path,
    extra_patterns: tuple[str, ...],
) -> bool:
    if path.resolve() in {output.resolve(), temporary_path.resolve()}:
        return True

    relative_path = path.relative_to(root)
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative_path.parts):
        return True

    filename = relative_path.name
    return any(
        fnmatch.fnmatch(filename, pattern)
        for pattern in (*EXCLUDED_FILE_PATTERNS, *extra_patterns)
    )


def create_lambda_zip(
    output: Path = DEFAULT_OUTPUT,
    source_root: Path = PROJECT_ROOT,
    extra_excludes: tuple[str, ...] = (),
) -> tuple[int, int]:
    root = source_root.resolve()
    archive_path = output.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Project source directory does not exist: {root}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with tempfile.NamedTemporaryFile(
        dir=archive_path.parent,
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)

    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
                current_directory = Path(directory)
                directories[:] = [
                    name for name in directories
                    if not (current_directory / name).is_symlink()
                    and not _should_exclude(
                        current_directory / name,
                        root,
                        archive_path,
                        temporary_path,
                        extra_excludes,
                    )
                ]
                for filename in filenames:
                    path = current_directory / filename
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or _should_exclude(
                            path,
                            root,
                            archive_path,
                            temporary_path,
                            extra_excludes,
                        )
                    ):
                        continue
                    archive.write(path, path.relative_to(root).as_posix())
                    file_count += 1
        os.replace(temporary_path, archive_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return file_count, archive_path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Lambda deployment ZIP, excluding secrets, databases, and local caches."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output ZIP path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Additional filename glob to exclude; can be specified more than once.",
    )
    args = parser.parse_args()
    file_count, archive_size = create_lambda_zip(
        output=args.output,
        extra_excludes=tuple(args.exclude),
    )
    print(
        f"Created {args.output.resolve()} with {file_count} files "
        f"({archive_size / (1024 * 1024):.2f} MiB)."
    )


if __name__ == "__main__":
    main()