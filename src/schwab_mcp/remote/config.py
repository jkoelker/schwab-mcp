"""Configuration for the remote MCP server loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from schwab_mcp.db import DatabaseConfig


@dataclass(frozen=True)
class RemoteServerConfig:
    """Configuration for the remote MCP Cloud Run service."""

    # Schwab API credentials
    schwab_client_id: str
    schwab_client_secret: str
    schwab_callback_url: str = "https://127.0.0.1:8182"
    schwab_base_url: str = "https://api.schwabapi.com"

    # Database (reuses existing Cloud SQL config)
    db_instance: str = ""
    db_name: str = "schwab_data"
    db_user: str = "agent_user"
    db_password: str = ""

    # OAuth for claude.ai authentication
    mcp_oauth_client_id: str = ""
    mcp_oauth_client_secret: str = ""

    # Server URL (set to the Cloud Run service URL)
    server_url: str = "http://localhost:8080"

    # Discord approval (optional)
    discord_token: str = ""
    discord_channel_id: int = 0
    discord_approvers: str = ""  # comma-separated user IDs
    discord_timeout: int = 600

    # Feature flags
    jesus_take_the_wheel: bool = False
    no_technical_tools: bool = False
    json_output: bool = True  # Default to JSON for remote

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    @classmethod
    def from_env(cls) -> RemoteServerConfig:
        """Load configuration from environment variables."""
        return cls(
            schwab_client_id=os.environ.get("SCHWAB_CLIENT_ID", ""),
            schwab_client_secret=os.environ.get("SCHWAB_CLIENT_SECRET", ""),
            schwab_callback_url=os.environ.get(
                "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"
            ),
            schwab_base_url=os.environ.get(
                "SCHWAB_BASE_URL", "https://api.schwabapi.com"
            ),
            db_instance=os.environ.get("SCHWAB_DB_INSTANCE", ""),
            db_name=os.environ.get("SCHWAB_DB_NAME", "schwab_data"),
            db_user=os.environ.get("SCHWAB_DB_USER", "agent_user"),
            db_password=os.environ.get("SCHWAB_DB_PASSWORD", ""),
            mcp_oauth_client_id=os.environ.get("MCP_OAUTH_CLIENT_ID", ""),
            mcp_oauth_client_secret=os.environ.get("MCP_OAUTH_CLIENT_SECRET", ""),
            server_url=os.environ.get("SERVER_URL", "http://localhost:8080"),
            discord_token=os.environ.get("SCHWAB_MCP_DISCORD_TOKEN", ""),
            discord_channel_id=int(
                os.environ.get("SCHWAB_MCP_DISCORD_CHANNEL_ID", "0")
            ),
            discord_approvers=os.environ.get("SCHWAB_MCP_DISCORD_APPROVERS", ""),
            discord_timeout=int(os.environ.get("SCHWAB_MCP_DISCORD_TIMEOUT", "600")),
            jesus_take_the_wheel=os.environ.get(
                "JESUS_TAKE_THE_WHEEL", ""
            ).lower()
            in ("1", "true", "yes"),
            no_technical_tools=os.environ.get("NO_TECHNICAL_TOOLS", "").lower()
            in ("1", "true", "yes"),
            json_output=os.environ.get("JSON_OUTPUT", "true").lower()
            in ("1", "true", "yes"),
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
        )

    @property
    def database_config(self) -> DatabaseConfig:
        """Create a DatabaseConfig from the remote server config."""
        return DatabaseConfig(
            instance_connection_name=self.db_instance,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )

    def validate(self) -> list[str]:
        """Return a list of validation errors, empty if valid."""
        errors: list[str] = []
        if not self.schwab_client_id:
            errors.append("SCHWAB_CLIENT_ID is required")
        if not self.schwab_client_secret:
            errors.append("SCHWAB_CLIENT_SECRET is required")
        if not self.db_instance:
            errors.append("SCHWAB_DB_INSTANCE is required")
        if not self.db_password:
            errors.append("SCHWAB_DB_PASSWORD is required")
        return errors


@dataclass(frozen=True)
class AdminConfig:
    """Configuration for the admin Cloud Run service."""

    # Schwab API credentials
    schwab_client_id: str
    schwab_client_secret: str
    schwab_callback_url: str = ""  # Must be set to admin service callback URL

    # Database (same Cloud SQL instance as MCP server)
    db_instance: str = ""
    db_name: str = "schwab_data"
    db_user: str = "agent_user"
    db_password: str = ""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    @classmethod
    def from_env(cls) -> AdminConfig:
        """Load configuration from environment variables."""
        return cls(
            schwab_client_id=os.environ.get("SCHWAB_CLIENT_ID", ""),
            schwab_client_secret=os.environ.get("SCHWAB_CLIENT_SECRET", ""),
            schwab_callback_url=os.environ.get("SCHWAB_CALLBACK_URL", ""),
            db_instance=os.environ.get("SCHWAB_DB_INSTANCE", ""),
            db_name=os.environ.get("SCHWAB_DB_NAME", "schwab_data"),
            db_user=os.environ.get("SCHWAB_DB_USER", "agent_user"),
            db_password=os.environ.get("SCHWAB_DB_PASSWORD", ""),
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
        )

    @property
    def database_config(self) -> DatabaseConfig:
        """Create a DatabaseConfig from the admin config."""
        return DatabaseConfig(
            instance_connection_name=self.db_instance,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )

    def validate(self) -> list[str]:
        """Return a list of validation errors, empty if valid."""
        errors: list[str] = []
        if not self.schwab_client_id:
            errors.append("SCHWAB_CLIENT_ID is required")
        if not self.schwab_client_secret:
            errors.append("SCHWAB_CLIENT_SECRET is required")
        if not self.schwab_callback_url:
            errors.append("SCHWAB_CALLBACK_URL is required (admin service callback URL)")
        if not self.db_instance:
            errors.append("SCHWAB_DB_INSTANCE is required")
        if not self.db_password:
            errors.append("SCHWAB_DB_PASSWORD is required")
        return errors
