#

import json
import pathlib
import os
from typing import Any, Callable

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
    pathlib.Path(data_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(data_dir, filename)


def token_writer(token_path: str) -> Callable[[dict[str, Any], ...], None]:
    """Create a function that writes token data to a file.

    This function creates a token writer that supports both JSON and YAML formats
    based on the file extension. If the filename ends with '.json', JSON format
    will be used; otherwise, YAML format will be used.

    Args:
        token_path: Path to the token file

    Returns:
        A function that takes a token dictionary and writes it to the file
    """

    def write_token(token: dict[str, Any], *args, **kwargs) -> None:
        """Write the token data to a file.

        Args:
            token: The OAuth token data dictionary
            *args: Additional arguments (ignored)
            **kwargs: Additional keyword arguments (ignored)
        """
        if not token:
            return

        with open(token_path, "w") as f:
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
