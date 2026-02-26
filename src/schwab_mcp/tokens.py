from __future__ import annotations

#

import json
import os
import pathlib
from typing import Any, Callable, Protocol

import yaml
from platformdirs import user_data_dir


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
    pathlib.Path(data_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.path.join(data_dir, filename)


class TokenWriter(Protocol):
    def __call__(self, token: dict[str, Any], *args: Any, **kwargs: Any) -> None: ...


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

        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w") as f:
            if token_path.endswith(".json"):
                return json.dump(token, f)

            # Round Trip the token through JSON to ensure it's serializable
            return yaml.safe_dump(
                json.loads(json.dumps(token)),
                f,
                default_flow_style=False,
                explicit_start=True,
            )

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
        with open(token_path, "r") as f:
            if token_path.endswith(".json"):
                return json.load(f)

            return yaml.safe_load(f)

    return load_token


class Manager:
    def __init__(self, path: str):
        self.path = path
        self.load = token_loader(self.path)
        self.write = token_writer(self.path)

    def exists(self) -> bool:
        return os.path.exists(self.path)


def credentials_path(app_name: str, filename: str = "credentials.yaml") -> str:
    """Get the path to the credentials file.

    Args:
        app_name: The application name
        filename: The credentials file name

    Returns:
        The path to the credentials file
    """
    data_dir = user_data_dir(app_name)
    pathlib.Path(data_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.path.join(data_dir, filename)


def load_credentials(path: str) -> dict[str, str]:
    """Load client credentials from a YAML file.

    Args:
        path: Path to the credentials file

    Returns:
        Dictionary with ``client_id`` and ``client_secret`` keys, or empty
        dict if the file does not exist.
    """
    if not os.path.exists(path):
        return {}

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return {}

    return data


def save_credentials(path: str, client_id: str, client_secret: str) -> None:
    """Write client credentials to a YAML file with restricted permissions.

    The file is created with ``0o600`` permissions so that only the owning
    user can read or write it.

    Args:
        path: Path to the credentials file
        client_id: Schwab client ID
        client_secret: Schwab client secret
    """
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(
            {"client_id": client_id, "client_secret": client_secret},
            f,
            default_flow_style=False,
            explicit_start=True,
        )
