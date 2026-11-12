"""Token and credentials persistence for the Schwab OAuth client."""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Any, Protocol

import yaml
from platformdirs import user_data_dir


def _private_dir(directory: str) -> None:
    """Create ``directory`` (and parents) with the leaf readable only by its owner."""
    pathlib.Path(directory).mkdir(mode=0o700, parents=True, exist_ok=True)


def _write_private_atomic(path: str, write: Callable[[IO[str]], None]) -> None:
    """Write a secret file owner-only (0600) and atomically.

    The content goes to a temp file created 0600 in the same directory, is
    flushed and fsynced, then ``os.replace``-d over ``path``. A crash or
    failed write leaves the previous file untouched, a pre-existing file with
    looser permissions is replaced rather than reused, and a symlink at
    ``path`` is replaced instead of written through.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise
    # Persist the rename itself; not supported on every platform.
    with contextlib.suppress(OSError):
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def token_path(app_name: str, filename: str = "token.yaml") -> str:
    """Get the path to the token file.

    This function returns the path to the token file based on the application name
    and the filename. The token file is stored in the user data directory.

    Args:
        app_name: The application name
        filename: The token file name

    Returns:
        The path to the token file
    """
    data_dir = user_data_dir(app_name)
    _private_dir(data_dir)
    return os.path.join(data_dir, filename)


class TokenWriter(Protocol):
    """Callable protocol for writing an OAuth token dictionary to storage."""

    def __call__(self, token: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Write *token* to the backing store."""
        ...


def token_writer(token_path: str) -> TokenWriter:
    """Create a function that writes token data to a file.

    This function creates a token writer that supports both JSON and YAML formats
    based on the file extension. If the filename ends with '.json', JSON format
    will be used; otherwise, YAML format will be used.

    Args:
        token_path: Path to the token file

    Returns:
        A function that takes a token dictionary and writes it to the file
    """

    def write_token(token: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Write the token data to a file.

        Args:
            token: The OAuth token data dictionary
            *args: Additional arguments (ignored)
            **kwargs: Additional keyword arguments (ignored)
        """
        if not token:
            return

        def dump(f: IO[str]) -> None:
            if token_path.endswith(".json"):
                json.dump(token, f)
                return

            # Round Trip the token through JSON to ensure it's serializable
            yaml.safe_dump(
                json.loads(json.dumps(token)),
                f,
                default_flow_style=False,
                explicit_start=True,
            )

        _write_private_atomic(token_path, dump)

    return write_token


def token_loader(token_path: str) -> Callable[[], dict[str, Any]]:
    """Create a function that loads token data from a file.

    This function creates a token loader that supports both JSON and YAML formats
    based on the file extension. If the filename ends with '.json', JSON format
    will be used; otherwise, YAML format will be used.

    Args:
        token_path: Path to the token file

    Returns:
        A function that loads and returns token data from the file
    """

    def load_token() -> dict[str, Any]:
        """Load the token data from a file.

        Returns:
            The OAuth token data as a dictionary
        """
        with open(token_path) as f:
            if token_path.endswith(".json"):
                return json.load(f)

            return yaml.safe_load(f)

    return load_token


class Manager:
    """Token manager that binds a file path to load and write callables."""

    def __init__(self, path: str) -> None:
        """Initialize the manager for the given token file path."""
        self.path = path
        self.load = token_loader(self.path)
        self.write = token_writer(self.path)

    def exists(self) -> bool:
        """Return True if the token file exists on disk."""
        return os.path.exists(self.path)


@dataclass(frozen=True)
class Credentials:
    """Schwab API client credentials loaded from a local credentials file."""

    client_id: str | None = None
    client_secret: str | None = None


def credentials_path(app_name: str, filename: str = "credentials.yaml") -> str:
    """Get the path to the credentials file.

    Args:
        app_name: The application name
        filename: The credentials file name

    Returns:
        The path to the credentials file
    """
    data_dir = user_data_dir(app_name)
    _private_dir(data_dir)
    return os.path.join(data_dir, filename)


def load_credentials(path: str) -> Credentials:
    """Load client credentials from a YAML file.

    Args:
        path: Path to the credentials file

    Returns:
        Credentials with None fields if the file does not exist or is invalid.
    """
    if not os.path.exists(path):
        return Credentials()

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return Credentials()

    client_id = data.get("client_id")
    client_secret = data.get("client_secret")

    return Credentials(
        client_id=client_id if isinstance(client_id, str) else None,
        client_secret=client_secret if isinstance(client_secret, str) else None,
    )


def save_credentials(path: str, client_id: str, client_secret: str) -> None:
    """Write client credentials to a YAML file with restricted permissions.

    The file is written atomically with ``0o600`` permissions so that only
    the owning user can read or write it, even if an older copy was looser.

    Args:
        path: Path to the credentials file
        client_id: Schwab client ID
        client_secret: Schwab client secret
    """
    _private_dir(str(pathlib.Path(path).parent))
    _write_private_atomic(
        path,
        lambda f: yaml.safe_dump(
            {"client_id": client_id, "client_secret": client_secret},
            f,
            default_flow_style=False,
            explicit_start=True,
        ),
    )
