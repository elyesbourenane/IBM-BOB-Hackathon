"""
Git abstraction for contract change detection and ref comparisons.

Uses the local git executable via subprocess without external library dependencies.
Gracefully handles environments where git is missing or the directory is not a git repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GitStatus:
    """Status and changed files in a git repository."""

    is_repo: bool
    repo_root: Optional[str] = None
    current_sha: Optional[str] = None
    base_ref: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    changed_contracts: list[str] = field(default_factory=list)
    other_changed_files: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_repo": self.is_repo,
            "repo_root": self.repo_root,
            "current_sha": self.current_sha,
            "base_ref": self.base_ref,
            "changed_files": self.changed_files,
            "changed_contracts": self.changed_contracts,
            "other_changed_files": self.other_changed_files,
            "error": self.error,
        }


def is_git_installed() -> bool:
    """Return True if the git executable is present in PATH."""
    return shutil.which("git") is not None


def _run_git(args: list[str], cwd: Path | str) -> tuple[int, str, str]:
    """
    Run a git command in the specified directory.
    Returns (returncode, stdout, stderr).
    Never raises an uncaught subprocess exception.
    """
    if not is_git_installed():
        return 127, "", "git executable not found in PATH"

    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def is_git_repo(path: Path | str) -> bool:
    """Check if *path* is inside a git repository."""
    p = Path(path).resolve()
    if not p.exists():
        return False
    rc, stdout, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=p if p.is_dir() else p.parent)
    return rc == 0 and stdout.strip() == "true"


def get_repo_root(path: Path | str) -> Path | None:
    """Return the absolute path to the root of the git repository containing *path*."""
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent
    rc, stdout, _ = _run_git(["rev-parse", "--show-toplevel"], cwd=target_dir)
    if rc == 0 and stdout.strip():
        return Path(stdout.strip()).resolve()
    return None


def get_current_sha(path: Path | str) -> str | None:
    """Return the current commit SHA (full 40 characters) or None."""
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent
    rc, stdout, _ = _run_git(["rev-parse", "HEAD"], cwd=target_dir)
    if rc == 0 and stdout.strip():
        return stdout.strip()
    return None


def get_short_sha(path: Path | str, length: int = 7) -> str | None:
    """Return short commit SHA or None."""
    sha = get_current_sha(path)
    if sha:
        return sha[:length]
    return None


def resolve_ref(path: Path | str, ref: str) -> str | None:
    """Resolve a git ref (e.g. 'origin/main', 'HEAD~1', 'v1.0.0') to a 40-char SHA."""
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent
    rc, stdout, _ = _run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=target_dir)
    if rc == 0 and stdout.strip():
        return stdout.strip()
    # Fallback to plain rev-parse in case ref^{commit} fails on some tags or trees
    rc2, stdout2, _ = _run_git(["rev-parse", ref], cwd=target_dir)
    if rc2 == 0 and stdout2.strip():
        return stdout2.strip()
    return None


def is_contract_file(filename: str | Path) -> bool:
    """
    Determine if a file path is likely an OpenAPI contract file.
    Matches paths with 'openapi', 'swagger', or 'contract' ending in .yaml or .yml.
    Excludes ContractGuard configuration files (e.g. contractguard.yaml).
    """
    p = Path(filename)
    lower_name = p.name.lower()
    lower_path = str(p).replace("\\", "/").lower()

    if p.suffix.lower() not in (".yaml", ".yml"):
        return False

    # ContractGuard workspace configuration file is not an OpenAPI contract
    if lower_name.startswith("contractguard"):
        return False

    posix_path = "/" + lower_path.lstrip("/")

    return (
        "openapi" in lower_name
        or "swagger" in lower_name
        or "contract" in lower_name
        or "/contracts/" in posix_path
        or "/docs/" in posix_path
    )


def get_changed_files(
    path: Path | str,
    base_ref: Optional[str] = None,
) -> tuple[list[str], Optional[str]]:
    """
    Get files changed in the repository relative to *base_ref* or the working tree.

    If *base_ref* is provided:
        Runs `git diff --name-only <base_ref>` to capture all changes since base_ref.
    If *base_ref* is None:
        First checks working tree against HEAD (`git status --porcelain`).
        If no uncommitted changes, falls back to the most recent commit (`git diff --name-only HEAD~1`).

    Returns:
        (list of repository-relative POSIX paths, error message if any)
    """
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent

    if not is_git_repo(target_dir):
        return [], f"Not a git repository: {target_dir}"

    repo_root = get_repo_root(target_dir)
    if not repo_root:
        return [], f"Could not determine git repository root for {target_dir}"

    changed: set[str] = set()

    if base_ref:
        resolved_base = resolve_ref(target_dir, base_ref)
        if not resolved_base:
            return [], f"Cannot resolve base ref: {base_ref!r}"

        rc, stdout, stderr = _run_git(["diff", "--name-only", base_ref], cwd=repo_root)
        if rc != 0:
            return [], f"git diff failed against {base_ref}: {stderr}"
        for line in stdout.splitlines():
            line = line.strip()
            if line:
                if line.startswith('"') and line.endswith('"'):
                    line = line[1:-1]
                changed.add(line.replace("\\", "/"))
    else:
        # Check uncommitted working tree and staged files
        rc, stdout, stderr = _run_git(["status", "--porcelain"], cwd=repo_root)
        if rc == 0 and stdout:
            for raw_line in stdout.splitlines():
                if not raw_line.strip():
                    continue
                # git status --porcelain format:
                # XY <path> or XY <orig_path> -> <path>
                # The first two characters indicate index/worktree status.
                # Character index 2 is usually a space separating status and path.
                filepath = raw_line[3:].strip() if len(raw_line) > 3 else raw_line[2:].strip()
                if not filepath:
                    continue
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[-1].strip()
                if filepath.startswith('"') and filepath.endswith('"'):
                    filepath = filepath[1:-1]
                changed.add(filepath.replace("\\", "/"))

        # If clean working tree, look at the most recent commit
        if not changed:
            rc2, stdout2, _ = _run_git(["diff", "--name-only", "HEAD~1", "HEAD"], cwd=repo_root)
            if rc2 == 0 and stdout2:
                for line in stdout2.splitlines():
                    line = line.strip()
                    if line:
                        if line.startswith('"') and line.endswith('"'):
                            line = line[1:-1]
                        changed.add(line.replace("\\", "/"))

    return sorted(changed), None


def get_file_content_at_ref(path: Path | str, file_rel_path: str, ref: str) -> Optional[str]:
    """
    Retrieve the content of *file_rel_path* (repo-relative) at *ref* via `git show <ref>:<path>`.
    Returns None if the file did not exist at *ref* or cannot be read.
    """
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent
    repo_root = get_repo_root(target_dir)
    if not repo_root:
        return None

    # git show expects forward slashes
    clean_path = str(file_rel_path).replace("\\", "/")
    rc, stdout, _ = _run_git(["show", f"{ref}:{clean_path}"], cwd=repo_root)
    if rc == 0:
        return stdout
    return None


def inspect_git_status(
    path: Path | str,
    base_ref: Optional[str] = None,
) -> GitStatus:
    """
    Perform a complete status check on the git repository at *path*.
    Identifies changed contract files and non-contract files.
    """
    p = Path(path).resolve()
    target_dir = p if p.is_dir() else p.parent

    if not is_git_installed():
        return GitStatus(is_repo=False, error="git executable not found in PATH")

    if not is_git_repo(target_dir):
        return GitStatus(is_repo=False, error=f"Not a git repository: {target_dir}")

    repo_root = get_repo_root(target_dir)
    current_sha = get_current_sha(target_dir)
    changed_files, err = get_changed_files(target_dir, base_ref=base_ref)

    if err:
        return GitStatus(
            is_repo=True,
            repo_root=str(repo_root) if repo_root else None,
            current_sha=current_sha,
            base_ref=base_ref,
            error=err,
        )

    changed_contracts = [f for f in changed_files if is_contract_file(f)]
    other_changed_files = [f for f in changed_files if f not in changed_contracts]

    return GitStatus(
        is_repo=True,
        repo_root=str(repo_root) if repo_root else None,
        current_sha=current_sha,
        base_ref=base_ref,
        changed_files=changed_files,
        changed_contracts=changed_contracts,
        other_changed_files=other_changed_files,
    )
