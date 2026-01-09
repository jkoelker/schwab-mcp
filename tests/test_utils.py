from __future__ import annotations

import pytest

from schwab_mcp.tools.utils import SchwabAPIError, call


class MockResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        url: str = "https://api.schwabapi.com/test",
        text: str = "",
        content: bytes = b"",
        json_data: dict | list | None = None,
        raise_error: bool = False,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.text = text
        self.content = content
        self._json_data = json_data
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error:
            raise Exception(f"HTTP {self.status_code}")

    def json(self) -> dict | list:
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


def run(coro):
    import asyncio

    return asyncio.run(coro)


class TestCall:
    def test_returns_json_payload_on_success(self):
        expected = {"symbol": "SPY", "price": 450.00}

        async def fake_endpoint():
            return MockResponse(
                json_data=expected,
                content=b'{"symbol": "SPY", "price": 450.00}',
            )

        result = run(call(fake_endpoint))
        assert result == expected

    def test_returns_list_json_payload(self):
        expected = [{"id": 1}, {"id": 2}]

        async def fake_endpoint():
            return MockResponse(
                json_data=expected,
                content=b'[{"id": 1}, {"id": 2}]',
            )

        result = run(call(fake_endpoint))
        assert result == expected

    def test_passes_args_and_kwargs_to_func(self):
        captured: dict = {}

        async def fake_endpoint(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return MockResponse(json_data={"ok": True}, content=b'{"ok": true}')

        run(call(fake_endpoint, "arg1", "arg2", key1="val1", key2="val2"))

        assert captured["args"] == ("arg1", "arg2")
        assert captured["kwargs"] == {"key1": "val1", "key2": "val2"}


class TestSchwabAPIError:
    def test_raises_on_error_status(self):
        async def fake_endpoint():
            return MockResponse(
                status_code=401,
                url="https://api.schwabapi.com/accounts",
                text='{"error": "Unauthorized"}',
                raise_error=True,
            )

        with pytest.raises(SchwabAPIError) as exc_info:
            run(call(fake_endpoint))

        error = exc_info.value
        assert "401" in str(error)
        assert "https://api.schwabapi.com/accounts" in str(error)
        assert "Unauthorized" in str(error)

    def test_error_message_includes_all_details(self):
        error = SchwabAPIError(
            status_code=500,
            url="https://api.schwabapi.com/orders",
            body="Internal Server Error",
        )

        msg = str(error)
        assert "status=500" in msg
        assert "url=https://api.schwabapi.com/orders" in msg
        assert "body=Internal Server Error" in msg

    def test_chains_original_exception(self):
        async def fake_endpoint():
            return MockResponse(
                status_code=403,
                url="https://api.schwabapi.com/test",
                text="Forbidden",
                raise_error=True,
            )

        with pytest.raises(SchwabAPIError) as exc_info:
            run(call(fake_endpoint))

        assert exc_info.value.__cause__ is not None


class TestResponseHandler:
    def test_returns_handler_payload_when_handled(self):
        custom_payload = {"custom": "response", "handled": True}

        def handler(response):
            return (True, custom_payload)

        async def fake_endpoint():
            return MockResponse(
                json_data={"ignored": True}, content=b'{"ignored": true}'
            )

        result = run(call(fake_endpoint, response_handler=handler))
        assert result == custom_payload

    def test_falls_through_to_json_when_not_handled(self):
        json_payload = {"from": "json"}

        def handler(response):
            return (False, None)

        async def fake_endpoint():
            return MockResponse(json_data=json_payload, content=b'{"from": "json"}')

        result = run(call(fake_endpoint, response_handler=handler))
        assert result == json_payload

    def test_handler_receives_response_object(self):
        captured_response = {}

        def handler(response):
            captured_response["status"] = response.status_code
            captured_response["url"] = response.url
            return (True, {"handled": True})

        async def fake_endpoint():
            return MockResponse(status_code=200, url="https://test.com/api")

        run(call(fake_endpoint, response_handler=handler))

        assert captured_response["status"] == 200
        assert captured_response["url"] == "https://test.com/api"


class TestNoContentResponses:
    @pytest.mark.parametrize("status_code", [201, 204])
    def test_returns_none_for_no_content_status_codes(self, status_code):
        async def fake_endpoint():
            return MockResponse(status_code=status_code, content=b"")

        result = run(call(fake_endpoint))
        assert result is None

    def test_returns_none_for_empty_content_with_200(self):
        async def fake_endpoint():
            return MockResponse(status_code=200, content=b"")

        result = run(call(fake_endpoint))
        assert result is None

    def test_returns_none_when_content_is_missing(self):
        class ResponseWithoutContent:
            status_code = 200
            url = "https://test.com"
            text = ""

            def raise_for_status(self):
                pass

        async def fake_endpoint():
            return ResponseWithoutContent()

        result = run(call(fake_endpoint))
        assert result is None


class TestJSONParseFailure:
    def test_raises_value_error_on_invalid_json(self):
        async def fake_endpoint():
            return MockResponse(
                status_code=200,
                content=b"not json",
                json_data=None,
            )

        with pytest.raises(ValueError, match="Expected JSON response"):
            run(call(fake_endpoint))

    def test_chains_original_json_error(self):
        async def fake_endpoint():
            return MockResponse(
                status_code=200,
                content=b"invalid",
                json_data=None,
            )

        with pytest.raises(ValueError) as exc_info:
            run(call(fake_endpoint))

        assert exc_info.value.__cause__ is not None
