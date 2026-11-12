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


# Existing loose data directories and secret files are tightened, not only new ones.


def _loose_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data" / "schwab-mcp"
    data_dir.mkdir(parents=True)
    data_dir.chmod(0o755)
    monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(data_dir))
    return data_dir


@posix_only
@pytest.mark.parametrize("path_fn", [tokens.token_path, tokens.credentials_path])
def test_existing_loose_data_directory_is_tightened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_fn) -> None:
    data_dir = _loose_data_dir(tmp_path, monkeypatch)

    path_fn("schwab-mcp")

    assert _mode(data_dir) == 0o700


@posix_only
@pytest.mark.parametrize(
    ("path_fn", "name"),
    [(tokens.token_path, "token.yaml"), (tokens.credentials_path, "credentials.yaml")],
)
def test_existing_loose_secret_file_in_data_directory_is_tightened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_fn, name: str
) -> None:
    data_dir = _loose_data_dir(tmp_path, monkeypatch)
    secret = data_dir / name
    secret.write_text("---\n")
    secret.chmod(0o644)

    assert path_fn("schwab-mcp") == str(secret)

    assert _mode(secret) == 0o600


@posix_only
@pytest.mark.parametrize("name", ["token.yaml", "token.json"])
def test_loading_loose_token_tightens_it(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    tokens.token_writer(str(path))(TOKEN)
    path.chmod(0o644)

    assert tokens.token_loader(str(path))() == TOKEN

    assert _mode(path) == 0o600


@posix_only
def test_loading_loose_credentials_tightens_them(tmp_path: Path) -> None:
    path = tmp_path / "credentials.yaml"
    tokens.save_credentials(str(path), "cid", "secret")
    path.chmod(0o644)

    assert tokens.load_credentials(str(path)) == tokens.Credentials("cid", "secret")

    assert _mode(path) == 0o600


@posix_only
def test_symlinked_secret_target_is_not_chmodded(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.yaml"
    target.write_text("---\nclient_id: cid\nclient_secret: secret\n")
    target.chmod(0o644)
    link = tmp_path / "credentials.yaml"
    link.symlink_to(target)

    tokens.load_credentials(str(link))

    assert _mode(target) == 0o644


@posix_only
def test_symlinked_data_directory_target_is_not_chmodded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shared"
    target.mkdir()
    target.chmod(0o755)
    link = tmp_path / "schwab-mcp"
    link.symlink_to(target)
    monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(link))

    tokens.token_path("schwab-mcp")

    assert _mode(target) == 0o755


@posix_only
def test_custom_token_parent_directory_is_left_alone(tmp_path: Path) -> None:
    parent = tmp_path / "projects"
    parent.mkdir()
    parent.chmod(0o755)
    path = parent / "token.yaml"
    tokens.token_writer(str(path))(TOKEN)

    tokens.token_loader(str(path))()

    assert _mode(parent) == 0o755
