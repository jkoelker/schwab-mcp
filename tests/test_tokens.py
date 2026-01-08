from __future__ import annotations

import json
import os
from typing import Any

import pytest
import yaml

from schwab_mcp import tokens


@pytest.fixture
def sample_token() -> dict[str, Any]:
    return {
        "access_token": "test_access_token_value",
        "refresh_token": "test_refresh_token_value",
        "token_type": "Bearer",
        "expires_in": 1800,
        "scope": "PlaceTrades AccountAccess MoveMoney",
        "expires_at": 1704067200.0,
        "refresh_token_expires_in": 604800,
        "refresh_token_expires_at": 1704672000.0,
    }


@pytest.fixture
def token_with_nested_data() -> dict[str, Any]:
    return {
        "access_token": "token123",
        "metadata": {
            "created_by": "test",
            "tags": ["automated", "test"],
        },
        "numeric_precision": 123.456789012345,
    }


@pytest.fixture(params=["token.json", "token.yaml", "token.yml"])
def token_path(request, tmp_path) -> str:
    return str(tmp_path / request.param)


@pytest.fixture
def json_token_path(tmp_path) -> str:
    return str(tmp_path / "token.json")


@pytest.fixture
def yaml_token_path(tmp_path) -> str:
    return str(tmp_path / "token.yaml")


class TestTokenPath:
    @pytest.fixture
    def mock_user_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(tmp_path))
        return tmp_path

    def test_returns_path_with_default_filename(self, mock_user_data_dir):
        result = tokens.token_path("test-app")

        assert result == str(mock_user_data_dir / "token.yaml")

    def test_returns_path_with_custom_filename(self, mock_user_data_dir):
        result = tokens.token_path("test-app", filename="custom.json")

        assert result == str(mock_user_data_dir / "custom.json")

    def test_creates_parent_directory_if_missing(self, monkeypatch, tmp_path):
        nested_dir = tmp_path / "nested" / "path"
        monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(nested_dir))

        result = tokens.token_path("test-app")

        assert nested_dir.exists()
        assert result == str(nested_dir / "token.yaml")

    def test_handles_existing_directory(self, monkeypatch, tmp_path):
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        monkeypatch.setattr(tokens, "user_data_dir", lambda app: str(existing_dir))

        result = tokens.token_path("test-app")

        assert result == str(existing_dir / "token.yaml")

    def test_uses_app_name_for_data_dir(self, monkeypatch, tmp_path):
        captured = {}
        monkeypatch.setattr(
            tokens,
            "user_data_dir",
            lambda app: captured.setdefault("app", app) or str(tmp_path),
        )

        tokens.token_path("schwab-mcp")

        assert captured["app"] == "schwab-mcp"


class TestTokenWriter:
    def test_writes_token_to_file(self, token_path, sample_token):
        writer = tokens.token_writer(token_path)

        writer(sample_token)

        assert os.path.exists(token_path)

    @pytest.mark.parametrize(
        ("extension", "expect_yaml_marker"),
        [
            (".json", False),
            (".yaml", True),
            (".yml", True),
        ],
    )
    def test_format_matches_extension(
        self, tmp_path, sample_token, extension, expect_yaml_marker
    ):
        path = str(tmp_path / f"token{extension}")
        writer = tokens.token_writer(path)

        writer(sample_token)

        with open(path) as f:
            content = f.read()

        assert content.startswith("---") == expect_yaml_marker

        if expect_yaml_marker:
            assert yaml.safe_load(content) == sample_token
        else:
            assert json.loads(content) == sample_token

    def test_empty_token_is_not_written(self, json_token_path):
        writer = tokens.token_writer(json_token_path)

        writer({})

        assert not os.path.exists(json_token_path)

    @pytest.mark.parametrize(
        ("args", "kwargs"),
        [
            (("ignored1", "ignored2"), {}),
            ((), {"some_kwarg": "ignored", "another": 123}),
        ],
        ids=["positional-args", "keyword-args"],
    )
    def test_ignores_extra_arguments(self, json_token_path, sample_token, args, kwargs):
        writer = tokens.token_writer(json_token_path)

        writer(sample_token, *args, **kwargs)

        assert os.path.exists(json_token_path)

    def test_preserves_nested_structures(self, json_token_path, token_with_nested_data):
        writer = tokens.token_writer(json_token_path)

        writer(token_with_nested_data)

        with open(json_token_path) as f:
            loaded = json.load(f)

        assert loaded["metadata"]["tags"] == ["automated", "test"]
        assert loaded["metadata"]["created_by"] == "test"

    def test_yaml_uses_block_style(self, yaml_token_path, sample_token):
        writer = tokens.token_writer(yaml_token_path)

        writer(sample_token)

        with open(yaml_token_path) as f:
            content = f.read()

        assert "access_token:" in content
        assert "refresh_token:" in content


class TestTokenLoader:
    @pytest.mark.parametrize(
        ("extension", "dump_fn"),
        [
            (".json", lambda f, data: json.dump(data, f)),
            (".yaml", lambda f, data: yaml.safe_dump(data, f)),
            (".yml", lambda f, data: yaml.safe_dump(data, f)),
        ],
    )
    def test_loads_file_by_extension(self, tmp_path, sample_token, extension, dump_fn):
        path = str(tmp_path / f"token{extension}")
        with open(path, "w") as f:
            dump_fn(f, sample_token)

        loader = tokens.token_loader(path)
        result = loader()

        assert result == sample_token

    def test_raises_on_missing_file(self, json_token_path):
        loader = tokens.token_loader(json_token_path)

        with pytest.raises(FileNotFoundError):
            loader()

    def test_raises_on_invalid_json(self, json_token_path):
        with open(json_token_path, "w") as f:
            f.write("{ invalid json }")

        loader = tokens.token_loader(json_token_path)

        with pytest.raises(json.JSONDecodeError):
            loader()

    def test_handles_yaml_with_explicit_start(self, yaml_token_path, sample_token):
        with open(yaml_token_path, "w") as f:
            yaml.safe_dump(sample_token, f, explicit_start=True)

        loader = tokens.token_loader(yaml_token_path)
        result = loader()

        assert result == sample_token


class TestRoundTrip:
    def test_preserves_data(self, token_path, sample_token):
        writer = tokens.token_writer(token_path)
        loader = tokens.token_loader(token_path)

        writer(sample_token)
        result = loader()

        assert result == sample_token

    def test_preserves_numeric_types(self, token_path):
        token = {"expires_in": 1800, "expires_at": 1704067200.123456}
        writer = tokens.token_writer(token_path)
        loader = tokens.token_loader(token_path)

        writer(token)
        result = loader()

        assert result["expires_in"] == 1800
        assert isinstance(result["expires_in"], int)
        assert result["expires_at"] == pytest.approx(1704067200.123456)

    def test_preserves_nested_data(self, token_path, token_with_nested_data):
        writer = tokens.token_writer(token_path)
        loader = tokens.token_loader(token_path)

        writer(token_with_nested_data)
        result = loader()

        assert result == token_with_nested_data


class TestManager:
    def test_init_sets_attributes(self, json_token_path):
        manager = tokens.Manager(json_token_path)

        assert manager.path == json_token_path
        assert callable(manager.load)
        assert callable(manager.write)

    def test_exists_returns_false_for_missing_file(self, json_token_path):
        manager = tokens.Manager(json_token_path)

        assert manager.exists() is False

    def test_exists_returns_true_for_existing_file(self, json_token_path, sample_token):
        with open(json_token_path, "w") as f:
            json.dump(sample_token, f)

        manager = tokens.Manager(json_token_path)

        assert manager.exists() is True

    def test_write_then_load_round_trip(self, json_token_path, sample_token):
        manager = tokens.Manager(json_token_path)

        manager.write(sample_token)
        result = manager.load()

        assert result == sample_token

    def test_write_creates_file(self, json_token_path, sample_token):
        manager = tokens.Manager(json_token_path)

        assert manager.exists() is False
        manager.write(sample_token)
        assert manager.exists() is True

    @pytest.mark.parametrize(
        ("filename", "expect_yaml"),
        [
            ("token.json", False),
            ("token.yaml", True),
            ("token.yml", True),
            ("my_token.JSON", True),
        ],
        ids=["json", "yaml", "yml", "uppercase-JSON-is-yaml"],
    )
    def test_format_detection_by_extension(
        self, tmp_path, sample_token, filename, expect_yaml
    ):
        path = str(tmp_path / filename)
        manager = tokens.Manager(path)

        manager.write(sample_token)

        with open(path) as f:
            content = f.read()

        assert content.startswith("---") == expect_yaml
