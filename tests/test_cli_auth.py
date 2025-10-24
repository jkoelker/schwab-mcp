from __future__ import annotations

from click.testing import CliRunner

from schwab_mcp import cli


def test_auth_command_uses_max_token_age(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class DummyManager:
        def __init__(self, path: str) -> None:
            self.path = path
            captured["token_path"] = path

    def fake_easy_client(**kwargs):
        captured["easy_client_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli.tokens, "Manager", DummyManager)
    monkeypatch.setattr(cli.schwab_auth, "easy_client", fake_easy_client)

    runner = CliRunner()
    token_file = tmp_path / "token.yaml"
    result = runner.invoke(
        cli.cli,
        [
            "auth",
            "--token-path",
            str(token_file),
            "--client-id",
            "cid",
            "--client-secret",
            "secret",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["token_path"] == str(token_file)
    assert captured["easy_client_kwargs"]["max_token_age"] == cli.TOKEN_MAX_AGE_SECONDS
