"""Token and credential files end up owner-only and are replaced atomically."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from schwab_mcp import tokens

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
TOKEN = {"creation_timestamp": 1, "token": {"access_token": "a", "refresh_token": "r"}}


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
@pytest.mark.parametrize("name", ["token.yaml", "token.json"])
def test_token_write_tightens_existing_loose_file(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("old")
    path.chmod(0o644)

    tokens.token_writer(str(path))(TOKEN)

    assert _mode(path) == 0o600
    assert tokens.token_loader(str(path))() == TOKEN


@posix_only
def test_credentials_write_tightens_existing_loose_file(tmp_path: Path) -> None:
    path = tmp_path / "credentials.yaml"
    path.write_text("old")
    path.chmod(0o644)

    tokens.save_credentials(str(path), "cid", "secret")

    assert _mode(path) == 0o600
    assert yaml.safe_load(path.read_text()) == {"client_id": "cid", "client_secret": "secret"}


def test_failed_token_write_keeps_previous_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "token.yaml"
    writer = tokens.token_writer(str(path))
    writer(TOKEN)
    before = path.read_text()

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tokens.yaml, "safe_dump", explode)

    with pytest.raises(OSError, match="disk full"):
        writer({"creation_timestamp": 2, "token": {"access_token": "new"}})

    assert path.read_text() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["token.yaml"]


def test_failed_credentials_write_keeps_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.yaml"
    tokens.save_credentials(str(path), "cid", "secret")
    before = path.read_text()

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tokens.yaml, "safe_dump", explode)

    with pytest.raises(OSError):
        tokens.save_credentials(str(path), "cid2", "secret2")

    assert path.read_text() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["credentials.yaml"]


@posix_only
@pytest.mark.parametrize("path_fn", [tokens.token_path, tokens.credentials_path])
def test_data_directory_created_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_fn) -> None:
    data_dir = tmp_path / "data" / "schwab-mcp"
    monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(data_dir))
    old_umask = os.umask(0o022)
    try:
        path_fn("schwab-mcp")
    finally:
        os.umask(old_umask)

    assert _mode(data_dir) == 0o700


@posix_only
def test_credentials_parent_created_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "new-dir" / "credentials.yaml"

    tokens.save_credentials(str(path), "cid", "secret")

    assert _mode(path.parent) == 0o700
