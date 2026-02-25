"""OAuth 2.1 provider for authenticating claude.ai to the MCP server.

This implements the OAuthAuthorizationServerProvider interface from the
MCP Python SDK. It provides a simple single-user OAuth flow:

1. claude.ai discovers endpoints via /.well-known/oauth-authorization-server
2. claude.ai registers dynamically via /register
3. claude.ai redirects user to /authorize (consent page)
4. User approves, gets redirected back with auth code
5. claude.ai exchanges code for access token at /token
6. claude.ai includes Bearer token in all /mcp requests

This is completely separate from Schwab OAuth. This layer only
authenticates claude.ai sessions to this Cloud Run server.
"""

from __future__ import annotations

import logging
import secrets
import time

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

# Token validity: 24 hours
ACCESS_TOKEN_TTL = 86400
# Auth code validity: 5 minutes
AUTH_CODE_TTL = 300
# Refresh token validity: 30 days
REFRESH_TOKEN_TTL = 30 * 86400


class SchwabMCPOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Single-user OAuth provider for the Schwab MCP server.

    Stores all state in memory. This is acceptable because:
    - Single user (you)
    - Cloud Run max instances = 1
    - If the instance restarts, claude.ai will re-auth (transparent to user)
    """

    def __init__(
        self,
        server_url: str,
        mcp_oauth_secret: str = "",
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.mcp_oauth_secret = mcp_oauth_secret

        # In-memory stores
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._state_mapping: dict[str, dict[str, str | None]] = {}

    async def get_client(
        self, client_id: str
    ) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        if not client_info.client_id:
            raise ValueError("No client_id provided")
        self._clients[client_info.client_id] = client_info
        logger.info("Registered OAuth client: %s", client_info.client_id)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Return a URL to the consent page."""
        state = params.state or secrets.token_hex(16)

        self._state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(
                params.redirect_uri_provided_explicitly
            ),
            "client_id": client.client_id,
            "resource": params.resource,
        }

        # Redirect to our consent page
        return f"{self.server_url}/consent?state={state}"

    async def get_consent_page(self, state: str) -> HTMLResponse:
        """Render a simple consent page for the user to approve."""
        if state not in self._state_mapping:
            return HTMLResponse(
                content="<h1>Invalid or expired state</h1>", status_code=400
            )

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Schwab MCP - Authorize</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 480px;
            margin: 40px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 32px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{ font-size: 1.4em; margin-top: 0; }}
        p {{ color: #555; line-height: 1.5; }}
        .actions {{ display: flex; gap: 12px; margin-top: 24px; }}
        button {{
            flex: 1;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
        }}
        .approve {{
            background: #2563eb;
            color: white;
        }}
        .approve:hover {{ background: #1d4ed8; }}
        .deny {{
            background: #e5e7eb;
            color: #374151;
        }}
        .deny:hover {{ background: #d1d5db; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Authorize Schwab MCP</h1>
        <p>Claude.ai is requesting access to your Schwab MCP server.
        This will allow Claude to use your Schwab brokerage tools
        (account info, quotes, options, orders).</p>
        <form action="{self.server_url}/consent/approve" method="post">
            <input type="hidden" name="state" value="{state}">
            <div class="actions">
                <button type="submit" name="action" value="approve" class="approve">
                    Approve
                </button>
                <button type="submit" name="action" value="deny" class="deny">
                    Deny
                </button>
            </div>
        </form>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html)

    async def handle_consent(self, request: Request) -> Response:
        """Process the consent form submission."""
        form = await request.form()
        state = form.get("state")
        action = form.get("action")

        if not isinstance(state, str) or state not in self._state_mapping:
            return HTMLResponse(
                content="<h1>Invalid or expired state</h1>", status_code=400
            )

        state_data = self._state_mapping[state]
        redirect_uri = state_data["redirect_uri"]

        if action != "approve":
            # Denied - redirect back with error
            assert redirect_uri is not None
            error_url = construct_redirect_uri(
                redirect_uri, error="access_denied", state=state
            )
            del self._state_mapping[state]
            return RedirectResponse(url=error_url, status_code=302)

        # Approved - generate auth code
        code_challenge = state_data["code_challenge"]
        redirect_uri_explicit = state_data["redirect_uri_provided_explicitly"] == "True"
        client_id = state_data["client_id"]
        resource = state_data.get("resource")

        assert redirect_uri is not None
        assert code_challenge is not None
        assert client_id is not None

        code = f"schwab_mcp_{secrets.token_hex(16)}"
        auth_code = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=AnyHttpUrl(redirect_uri),
            redirect_uri_provided_explicitly=redirect_uri_explicit,
            expires_at=time.time() + AUTH_CODE_TTL,
            scopes=["mcp"],
            code_challenge=code_challenge,
            resource=resource,
        )
        self._auth_codes[code] = auth_code

        del self._state_mapping[state]

        final_url = construct_redirect_uri(redirect_uri, code=code, state=state)
        return RedirectResponse(url=final_url, status_code=302)

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        return self._auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        if authorization_code.code not in self._auth_codes:
            raise ValueError("Invalid authorization code")
        if not client.client_id:
            raise ValueError("No client_id provided")

        # Generate tokens
        access_token_str = f"smcp_at_{secrets.token_hex(32)}"
        refresh_token_str = f"smcp_rt_{secrets.token_hex(32)}"
        now = int(time.time())

        self._access_tokens[access_token_str] = AccessToken(
            token=access_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + ACCESS_TOKEN_TTL,
            resource=authorization_code.resource,
        )

        self._refresh_tokens[refresh_token_str] = RefreshToken(
            token=refresh_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
            resource=authorization_code.resource,
        )

        del self._auth_codes[authorization_code.code]

        logger.info("Issued access token for client %s", client.client_id)

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_token_str,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self._access_tokens.get(token)
        if not access_token:
            return None

        if access_token.expires_at and access_token.expires_at < time.time():
            del self._access_tokens[token]
            return None

        return access_token

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if not rt:
            return None

        if rt.expires_at and rt.expires_at < time.time():
            del self._refresh_tokens[refresh_token]
            return None

        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not client.client_id:
            raise ValueError("No client_id provided")

        # Revoke old refresh token
        if refresh_token.token in self._refresh_tokens:
            del self._refresh_tokens[refresh_token.token]

        # Issue new tokens
        access_token_str = f"smcp_at_{secrets.token_hex(32)}"
        new_refresh_str = f"smcp_rt_{secrets.token_hex(32)}"
        now = int(time.time())

        effective_scopes = scopes or refresh_token.scopes

        self._access_tokens[access_token_str] = AccessToken(
            token=access_token_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=now + ACCESS_TOKEN_TTL,
        )

        self._refresh_tokens[new_refresh_str] = RefreshToken(
            token=new_refresh_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
        )

        logger.info("Refreshed access token for client %s", client.client_id)

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=new_refresh_str,
            scope=" ".join(effective_scopes),
        )

    async def revoke_token(
        self, token: str, token_type_hint: str | None = None
    ) -> None:
        # Remove from both stores
        self._access_tokens.pop(token, None)
        self._refresh_tokens.pop(token, None)
