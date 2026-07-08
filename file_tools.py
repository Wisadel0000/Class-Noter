from langchain.tools import tool
from pathlib import Path
import os
import config

path = os.getenv("NOTE_ROOT_PATH")
ROOT_DIR = Path(path).resolve()


def _resolve_path(relative_path: str) -> Path:
    """Resolve a relative path against ROOT_DIR and prevent path traversal."""
    resolved = (ROOT_DIR / relative_path).resolve()
    if not str(resolved).startswith(str(ROOT_DIR)):
        raise ValueError(f"Path traversal detected: '{relative_path}' escapes the root directory")
    return resolved


@tool
def create_md_file(relative_path: str, content: str = "") -> str:
    """Create a .md file at the given relative path under the root directory.
    Creates parent directories if they don't exist."""
    if not relative_path.endswith(".md"):
        raise ValueError("Only .md files can be created")
    path = _resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Created: {relative_path}"


@tool
def delete_md_file(relative_path: str) -> str:
    """Delete a .md file at the given relative path under the root directory."""
    if not relative_path.endswith(".md"):
        raise ValueError("Only .md files can be deleted")
    path = _resolve_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {relative_path}")
    path.unlink()
    return f"Deleted: {relative_path}"


@tool
def read_md_file(relative_path: str) -> str:
    """Read and return the content of a .md file at the given relative path."""
    if not relative_path.endswith(".md"):
        raise ValueError("Only .md files can be read")
    path = _resolve_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {relative_path}")
    return path.read_text(encoding="utf-8")


@tool
def overwrite_md_file(relative_path: str, content: str) -> str:
    """Overwrite a .md file at the given relative path with new content.
    Creates the file if it doesn't exist."""
    if not relative_path.endswith(".md"):
        raise ValueError("Only .md files can be overwritten")
    path = _resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Overwritten: {relative_path}"


@tool
def move_md_file(relative_source: str, relative_destination: str) -> str:
    """Move/rename a .md file from relative_source to relative_destination."""
    if not relative_source.endswith(".md") or not relative_destination.endswith(".md"):
        raise ValueError("Only .md files can be moved")
    src = _resolve_path(relative_source)
    dst = _resolve_path(relative_destination)
    if not src.exists():
        raise FileNotFoundError(f"File not found: {relative_source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return f"Moved: {relative_source} -> {relative_destination}"


@tool
def create_directory(relative_path: str) -> str:
    """Create a directory at the given relative path under the root directory.
    Creates parent directories if they don't exist."""
    path = _resolve_path(relative_path)
    path.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {relative_path}"


@tool
def delete_directory(relative_path: str) -> str:
    """Delete an empty directory at the given relative path."""
    path = _resolve_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {relative_path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {relative_path}")
    path.rmdir()
    return f"Deleted directory: {relative_path}"


@tool
def list_directory(relative_path: str = "") -> str:
    """List all files and subdirectories inside the given relative directory.
    If relative_path is empty or '.', lists the root directory."""
    path = _resolve_path(relative_path or ".")
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {relative_path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {relative_path}")

    items = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
        suffix = "/" if entry.is_dir() else ""
        items.append(f"  {entry.name}{suffix}")
    header = f"Contents of: {relative_path or '.'}\n"
    return header + "\n".join(items) if items else header + "(empty)"


@tool
def move_directory(relative_source: str, relative_destination: str) -> str:
    """Move/rename a directory from relative_source to relative_destination."""
    src = _resolve_path(relative_source)
    dst = _resolve_path(relative_destination)
    if not src.exists():
        raise FileNotFoundError(f"Directory not found: {relative_source}")
    if not src.is_dir():
        raise NotADirectoryError(f"Not a directory: {relative_source}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return f"Moved directory: {relative_source} -> {relative_destination}"


@tool
def rename_md_file(relative_path: str, new_name: str) -> str:
    """Rename a .md file. relative_path is the current path, new_name is the new filename
    (e.g., 'old.md' -> 'new.md'). The file stays in the same directory."""
    if not relative_path.endswith(".md") or not new_name.endswith(".md"):
        raise ValueError("Only .md files can be renamed")
    src = _resolve_path(relative_path)
    dst = src.with_name(new_name)
    if not src.exists():
        raise FileNotFoundError(f"File not found: {relative_path}")
    if dst.exists():
        raise FileExistsError(f"Target already exists: {dst.name}")
    src.rename(dst)
    return f"Renamed: {relative_path} -> {dst.name}"


@tool
def rename_directory(relative_path: str, new_name: str) -> str:
    """Rename a directory. relative_path is the current path, new_name is the new folder name.
    The directory stays in the same parent."""
    src = _resolve_path(relative_path)
    dst = src.with_name(new_name)
    if not src.exists():
        raise FileNotFoundError(f"Directory not found: {relative_path}")
    if not src.is_dir():
        raise NotADirectoryError(f"Not a directory: {relative_path}")
    if dst.exists():
        raise FileExistsError(f"Target already exists: {new_name}")
    src.rename(dst)
    return f"Renamed directory: {relative_path} -> {new_name}"


@tool
def list_all_directories() -> str:
    """Recursively list all directories and subdirectories under the root directory."""
    lines = []
    for root, dirs, _ in os.walk(ROOT_DIR):
        rel = Path(root).relative_to(ROOT_DIR)
        depth = len(rel.parts)
        indent = "  " * depth
        folder_name = rel.name if str(rel) != "." else "."
        lines.append(f"{indent}{folder_name}/")
    return "Root directory tree:\n" + "\n".join(lines) if lines else "Root directory tree:\n(empty)"
