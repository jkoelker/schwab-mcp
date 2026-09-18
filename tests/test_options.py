import datetime
from typing import Any

import pytest
from conftest import make_ctx, run
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError
from mcp.server.mcpserver import MCPServer
from schwab.client import AsyncClient

from schwab_mcp.tools import options


class DummyOptionsClient:
    """Provide option endpoint stubs using the installed Schwab SDK enums."""

    Options = AsyncClient.Options

    async def get_option_chain(self, *args, **kwargs):
        """Return no payload for a stubbed option-chain request."""
        return None

    async def get_option_expiration_chain(self, *args, **kwargs):
        """Return no payload for a stubbed expiration request."""
        return None


def _enum_schema_choices(enum_type: Any) -> tuple[str, ...]:
    """Return the SDK enum member names advertised by the option tools."""
    return tuple(member.name for member in enum_type)


@pytest.mark.parametrize(
    ("tool_names", "parameter", "choices"),
    (
        (
            ("get_option_chain", "get_advanced_option_chain"),
            "contract_type",
            _enum_schema_choices(AsyncClient.Options.ContractType),
        ),
        (
            ("get_advanced_option_chain",),
            "strategy",
            _enum_schema_choices(AsyncClient.Options.Strategy),
        ),
        (
            ("get_advanced_option_chain",),
            "strike_range",
            _enum_schema_choices(AsyncClient.Options.StrikeRange),
        ),
        (
            ("get_advanced_option_chain",),
            "exp_month",
            _enum_schema_choices(AsyncClient.Options.ExpirationMonth),
        ),
        (
            ("get_advanced_option_chain",),
            "option_type",
            _enum_schema_choices(AsyncClient.Options.Type),
        ),
    ),
)
def test_registered_option_enum_schema(
    tool_names: tuple[str, ...],
    parameter: str,
    choices: tuple[str, ...],
) -> None:
    """Expose only advertised enum choices and reject invalid MCP inputs."""
    server = MCPServer(name="options-enum-schema")
    options.register(server, allow_write=False)
    registered_tools = {tool.name: tool for tool in run(server.list_tools())}

    for tool_name in tool_names:
        tool = registered_tools[tool_name]
        branches = tool.input_schema["properties"][parameter]["anyOf"]
        enum_branches = [branch for branch in branches if "enum" in branch]
        assert enum_branches == [{"enum": list(choices), "type": "string"}]
        assert all("enum" in branch or branch.get("type") == "null" for branch in branches)

        validator = Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
        validator.validate({"symbol": "SPY", parameter: choices[0]})
        with pytest.raises(JSONSchemaValidationError):
            validator.validate({"symbol": "SPY", parameter: "invalid"})


def test_registered_option_tools_expose_parameter_schemas():
    """Expose enum choices, ISO date branches, and narrowing guidance in MCP schemas."""
    server = MCPServer(name="options-schema")
    options.register(server, allow_write=False)

    registered_tools = {tool.name: tool for tool in run(server.list_tools())}
    assert set(registered_tools) == {
        "get_option_chain",
        "get_advanced_option_chain",
        "get_option_expiration_chain",
    }

    standard_tool = registered_tools["get_option_chain"]
    advanced_tool = registered_tools["get_advanced_option_chain"]
    expiration_tool = registered_tools["get_option_expiration_chain"]
    standard_schema = standard_tool.input_schema
    advanced_schema = advanced_tool.input_schema
    expiration_schema = expiration_tool.input_schema

    for schema in (standard_schema, advanced_schema, expiration_schema):
        assert all("description" in property_schema for property_schema in schema["properties"].values())

    for schema in (standard_schema, advanced_schema):
        assert "include_underlying_quote" in schema["properties"]
        assert "include_quotes" not in schema["properties"]
        for parameter in ("from_date", "to_date"):
            date_branches = [
                branch
                for branch in schema["properties"][parameter]["anyOf"]
                if branch.get("type") == "string" and branch.get("format") == "date"
            ]
            assert date_branches == [{"format": "date", "type": "string"}]
            assert all(
                branch == {"format": "date", "type": "string"} or branch == {"type": "null"}
                for branch in schema["properties"][parameter]["anyOf"]
            )

    assert standard_tool.description == options.get_option_chain.__doc__
    assert advanced_tool.description == options.get_advanced_option_chain.__doc__
    assert expiration_tool.description == options.get_option_expiration_chain.__doc__

    for tool in (standard_tool, advanced_tool):
        validator = Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
        validator.validate(
            {
                "symbol": "SPY",
                "from_date": "2024-05-01",
                "to_date": "2024-06-01",
            }
        )
        with pytest.raises(JSONSchemaValidationError):
            validator.validate({"symbol": "SPY", "from_date": "2024-99-99"})


def test_get_advanced_option_chain_parses_and_maps_parameters(monkeypatch, fake_call_factory):
    """Map advertised uppercase option filters to the matching SDK enums."""
    captured, fake_call = fake_call_factory()

    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(
        options.get_advanced_option_chain(
            ctx,
            "SPY",
            contract_type="PUT",
            strike_count=10,
            include_underlying_quote=True,
            strategy="VERTICAL",
            interval="2",
            strike=420.0,
            strike_range="NEAR_THE_MONEY",
            from_date=datetime.date(2024, 5, 1),
            to_date=datetime.date(2024, 6, 1),
            volatility=0.25,
            underlying_price=415.5,
            interest_rate=0.03,
            days_to_expiration=30,
            exp_month="JANUARY",
            option_type="STANDARD",
        )
    )

    assert result == "ok"
    assert captured["func"] == client.get_option_chain

    args = captured["args"]
    assert isinstance(args, tuple)
    assert args == ("SPY",)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["contract_type"] is client.Options.ContractType.PUT
    assert kwargs["strike_count"] == 10
    assert kwargs["include_underlying_quote"] is True
    assert kwargs["strategy"] is client.Options.Strategy.VERTICAL
    assert kwargs["interval"] == "2"
    assert kwargs["strike"] == 420.0
    assert kwargs["strike_range"] is client.Options.StrikeRange.NEAR_THE_MONEY
    assert kwargs["from_date"] == datetime.date(2024, 5, 1)
    assert kwargs["to_date"] == datetime.date(2024, 6, 1)
    assert kwargs["volatility"] == 0.25
    assert kwargs["underlying_price"] == 415.5
    assert kwargs["interest_rate"] == 0.03
    assert kwargs["days_to_expiration"] == 30
    assert kwargs["exp_month"] is client.Options.ExpirationMonth.JANUARY
    assert kwargs["option_type"] is client.Options.Type.STANDARD


def test_parse_strike_range_rejects_invalid_input():
    """Raise an actionable error when a strike-range value is invalid."""
    with pytest.raises(ValueError) as exc_info:
        options._parse_strike_range(DummyOptionsClient(), "invalid")

    assert str(exc_info.value) == (
        "Invalid strike_range: invalid. Must be one of: IN_THE_MONEY, NEAR_THE_MONEY, "
        "OUT_OF_THE_MONEY, STRIKES_ABOVE_MARKET, STRIKES_BELOW_MARKET, STRIKES_NEAR_MARKET, ALL"
    )


# ---------------------------------------------------------------------------
# _prune_contract / _prune_option_chain helpers
# ---------------------------------------------------------------------------

_SAMPLE_CONTRACT = {
    "strike": 420.0,
    "bid": 1.5,
    "ask": 1.6,
    "last": 1.55,
    "mark": 1.55,
    "bidSize": 10,
    "askSize": 20,
    "volume": 500,
    "openInterest": 1000,
    "delta": -0.35,
    "gamma": 0.05,
    "theta": -0.02,
    "vega": 0.1,
    "rho": 0.01,
    "impliedVolatility": 0.25,
    "inTheMoney": False,
    "expirationDate": "2024-06-21",
    "daysToExpiration": 30,
    "expirationType": "R",
    # Extra fields that should be stripped
    "description": "SPY Jun 21 2024 420 Put",
    "exchangeName": "OPR",
    "settlementType": " ",
    "deliverableNote": "",
}


def test_prune_contract_keeps_compact_fields():
    pruned = options._prune_contract(_SAMPLE_CONTRACT)
    assert set(pruned.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert pruned["strike"] == 420.0
    assert pruned["delta"] == -0.35
    assert "description" not in pruned
    assert "exchangeName" not in pruned


def _make_chain_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": "SPY",
        "callExpDateMap": {
            "2024-06-21:30": {
                "420.0": [contract],
            }
        },
        "putExpDateMap": {
            "2024-06-21:30": {
                "420.0": [contract],
            }
        },
    }


def test_prune_option_chain_default_prunes_contracts(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_make_chain_payload(_SAMPLE_CONTRACT))
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_option_chain(ctx, "SPY"))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    put_contract = result["putExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert set(call_contract.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert set(put_contract.keys()) == options._COMPACT_CONTRACT_FIELDS
    assert "description" not in call_contract


def test_prune_option_chain_verbose_returns_raw(monkeypatch, fake_call_factory):
    payload = _make_chain_payload(_SAMPLE_CONTRACT)
    _, fake_call = fake_call_factory(return_value=payload)
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_option_chain(ctx, "SPY", verbose=True))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert "description" in call_contract


def test_prune_option_chain_advanced_default_prunes(monkeypatch, fake_call_factory):
    _, fake_call = fake_call_factory(return_value=_make_chain_payload(_SAMPLE_CONTRACT))
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_advanced_option_chain(ctx, "SPY"))

    assert isinstance(result, dict)
    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert set(call_contract.keys()) == options._COMPACT_CONTRACT_FIELDS


def test_prune_option_chain_advanced_verbose_returns_raw(monkeypatch, fake_call_factory):
    payload = _make_chain_payload(_SAMPLE_CONTRACT)
    _, fake_call = fake_call_factory(return_value=payload)
    monkeypatch.setattr(options, "call", fake_call)

    client = DummyOptionsClient()
    ctx = make_ctx(client)
    result = run(options.get_advanced_option_chain(ctx, "SPY", verbose=True))

    call_contract = result["callExpDateMap"]["2024-06-21:30"]["420.0"][0]
    assert "description" in call_contract


def test_prune_option_chain_non_dict_payload_passthrough():
    assert options._prune_option_chain("not a dict") == "not a dict"
    assert options._prune_option_chain(None) is None
    assert options._prune_option_chain([1, 2, 3]) == [1, 2, 3]


def test_prune_option_chain_missing_exp_maps_passthrough():
    payload = {"symbol": "SPY", "status": "SUCCESS"}
    result = options._prune_option_chain(payload)
    assert result == {"symbol": "SPY", "status": "SUCCESS"}


def test_prune_option_chain_malformed_exp_map_no_raise():
    payload = {
        "callExpDateMap": "oops",
        "putExpDateMap": {"2024-06-21:30": "not-a-dict"},
    }
    # Should not raise, return payload unchanged for bad shapes
    result = options._prune_option_chain(payload)
    assert result is payload
