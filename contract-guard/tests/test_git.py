"""Tests for the git abstraction module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from contract_guard.git import (
    get_changed_files,
    get_current_sha,
    get_file_content_at_ref,
    get_repo_root,
    get_short_sha,
    inspect_git_status,
    is_contract_file,
    is_git_installed,
    is_git_repo,
    resolve_ref,
)


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with user info configured."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)


def test_is_git_installed():
    assert is_git_installed() is True


def test_missing_git_executable_handling(tmp_path: Path):
    with patch("contract_guard.git.is_git_installed", return_value=False):
        status = inspect_git_status(tmp_path)
        assert status.is_repo is False
        assert "not found" in status.error


def test_non_git_directory(tmp_path: Path):
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    assert is_git_repo(non_git) is False
    assert get_repo_root(non_git) is None
    assert get_current_sha(non_git) is None

    status = inspect_git_status(non_git)
    assert status.is_repo is False
    assert "Not a git repository" in status.error


def test_valid_git_repository(tmp_path: Path):
    repo_dir = tmp_path / "my_repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    assert is_git_repo(repo_dir) is True
    root = get_repo_root(repo_dir)
    assert root == repo_dir.resolve()

    # Create initial commit
    f1 = repo_dir / "README.md"
    f1.write_text("# Hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)

    sha = get_current_sha(repo_dir)
    assert sha is not None
    assert len(sha) == 40
    short_sha = get_short_sha(repo_dir, 7)
    assert short_sha == sha[:7]

    # Resolve refs
    resolved_head = resolve_ref(repo_dir, "HEAD")
    assert resolved_head == sha
    assert resolve_ref(repo_dir, "non_existent_ref_xyz") is None


def test_changed_files_detection(tmp_path: Path):
    repo_dir = tmp_path / "diff_repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    # Initial commit
    (repo_dir / "openapi.yaml").write_text("version: 1.0", encoding="utf-8")
    (repo_dir / "Service.java").write_text("class Service {}", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=repo_dir, check=True, capture_output=True)

    c1_sha = get_current_sha(repo_dir)

    # Modify contract and add new file
    (repo_dir / "openapi.yaml").write_text("version: 2.0", encoding="utf-8")
    (repo_dir / "Extra.java").write_text("class Extra {}", encoding="utf-8")

    # 1. Uncommitted working tree diff
    changed, err = get_changed_files(repo_dir)
    assert err is None
    assert any("openapi.yaml" in f for f in changed)
    assert any("Extra.java" in f for f in changed)

    # 2. Inspect git status
    status = inspect_git_status(repo_dir)
    assert status.is_repo is True
    assert len(status.changed_contracts) == 1
    assert "openapi.yaml" in status.changed_contracts[0]
    assert len(status.other_changed_files) >= 1

    # Commit the changes
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=repo_dir, check=True, capture_output=True)

    # 3. Base ref diff against commit 1
    changed_base, err2 = get_changed_files(repo_dir, base_ref=c1_sha)
    assert err2 is None
    assert "openapi.yaml" in changed_base
    assert "Extra.java" in changed_base

    # 4. Read file content at ref
    c1_content = get_file_content_at_ref(repo_dir, "openapi.yaml", c1_sha)
    assert c1_content is not None
    assert "version: 1.0" in c1_content


def test_invalid_base_ref(tmp_path: Path):
    repo_dir = tmp_path / "err_repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True)

    changed, err = get_changed_files(repo_dir, base_ref="invalid_branch_or_sha")
    assert changed == []
    assert "Cannot resolve base ref" in err

    status = inspect_git_status(repo_dir, base_ref="invalid_branch_or_sha")
    assert status.error is not None
    assert "Cannot resolve base ref" in status.error


def test_is_contract_file():
    assert is_contract_file("docs/openapi.yaml") is True
    assert is_contract_file("contracts/payment-service.yml") is True
    assert is_contract_file("swagger.yaml") is True
    assert is_contract_file("api/contracts/service.yaml") is True
    assert is_contract_file("README.md") is False
    assert is_contract_file("PaymentResponse.java") is False
    assert is_contract_file("pom.xml") is False
    assert is_contract_file("contractguard.yaml") is False  # Config, not OpenAPI contract
