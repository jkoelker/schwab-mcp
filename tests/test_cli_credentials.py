from __future__ import annotations

import os

import yaml

from schwab_mcp import cli


class TestAuthCredentialsFile:
    def test_falls_back_to_credentials_file(
        self,
        cli_auth_capture,
        cli_credentials_writer,
        cli_runner,
        cli_credentials_file,
    ):
        """Use credentials loaded from the configured credentials file."""
        captured = cli_auth_capture
        cli_credentials_writer("file-id", "file-secret")

        result = cli_runner.invoke(
            cli.cli,
            ["auth", "--token-path", str(cli_credentials_file.with_name("token.yaml"))],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "file-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "file-secret"

    def test_cli_args_override_credentials_file(
        self,
        cli_auth_capture,
        cli_credentials_writer,
        cli_runner,
        cli_credentials_file,
    ):
        """Prefer explicit CLI credentials over values from the credentials file."""
        captured = cli_auth_capture
        cli_credentials_writer("file-id", "file-secret")

        result = cli_runner.invoke(
            cli.cli,
            [
                "auth",
                "--token-path",
                str(cli_credentials_file.with_name("token.yaml")),
                "--client-id",
                "cli-id",
                "--client-secret",
                "cli-secret",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "cli-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "cli-secret"

    def test_errors_when_no_credentials_available(
        self,
        cli_runner,
        cli_credentials_file,
    ):
        """Reject authentication when neither CLI nor file credentials exist."""
        result = cli_runner.invoke(
            cli.cli,
            ["auth", "--token-path", str(cli_credentials_file.with_name("t.yaml"))],
        )

        assert result.exit_code == 1
        assert "client-id and client-secret are required" in result.output


class TestServerCredentialsFile:
    def test_falls_back_to_credentials_file(
        self,
        cli_server_capture,
        cli_credentials_writer,
        cli_runner,
        cli_credentials_file,
    ):
        """Use credentials loaded from the configured credentials file."""
        captured = cli_server_capture
        cli_credentials_writer("file-id", "file-secret")

        result = cli_runner.invoke(
            cli.cli,
            [
                "server",
                "--token-path",
                str(cli_credentials_file.with_name("token.yaml")),
                "--jesus-take-the-wheel",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "file-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "file-secret"

    def test_cli_args_override_credentials_file(
        self,
        cli_server_capture,
        cli_credentials_writer,
        cli_runner,
        cli_credentials_file,
    ):
        """Prefer explicit CLI credentials over values from the credentials file."""
        captured = cli_server_capture
        cli_credentials_writer("file-id", "file-secret")

        result = cli_runner.invoke(
            cli.cli,
            [
                "server",
                "--token-path",
                str(cli_credentials_file.with_name("token.yaml")),
                "--client-id",
                "cli-id",
                "--client-secret",
                "cli-secret",
                "--jesus-take-the-wheel",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert captured["easy_client_kwargs"]["client_id"] == "cli-id"
        assert captured["easy_client_kwargs"]["client_secret"] == "cli-secret"

    def test_errors_when_no_credentials_available(
        self,
        cli_server_capture,
        cli_runner,
        cli_credentials_file,
    ):
        """Reject server startup before attempting client authentication."""
        captured = cli_server_capture
        result = cli_runner.invoke(
            cli.cli,
            ["server", "--token-path", str(cli_credentials_file.with_name("t.yaml"))],
        )

        assert result.exit_code == 1
        assert "client-id and client-secret are required" in result.output
        assert "easy_client_called" not in captured


class TestSaveCredentialsCommand:
    def test_saves_credentials_with_prompts(self, cli_credentials_file, cli_runner):
        """Save credentials supplied through interactive prompts."""
        result = cli_runner.invoke(
            cli.cli,
            ["save-credentials"],
            input="my-client-id\nmy-client-secret\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Credentials saved to:" in result.output

        with cli_credentials_file.open() as credentials:
            data = yaml.safe_load(credentials)

        assert data == {
            "client_id": "my-client-id",
            "client_secret": "my-client-secret",
        }

    def test_saves_credentials_with_flags(self, cli_credentials_file, cli_runner):
        """Save credentials supplied through command-line flags."""
        result = cli_runner.invoke(
            cli.cli,
            [
                "save-credentials",
                "--client-id",
                "flag-id",
                "--client-secret",
                "flag-secret",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0

        with cli_credentials_file.open() as credentials:
            data = yaml.safe_load(credentials)

        assert data == {"client_id": "flag-id", "client_secret": "flag-secret"}

    def test_file_has_restricted_permissions(self, cli_credentials_file, cli_runner):
        """Create the credentials file with owner-only permissions."""
        cli_runner.invoke(
            cli.cli,
            ["save-credentials", "--client-id", "id", "--client-secret", "secret"],
            catch_exceptions=False,
        )

        mode = os.stat(cli_credentials_file).st_mode & 0o777
        assert mode == 0o600
