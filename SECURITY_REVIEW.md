# Security Review Report — schwab-mcp

**Date:** 2026-02-26
**Scope:** Full codebase review of `schwab-mcp` (commit on branch `main`)
**Reviewer:** Automated security analysis

---

## Executive Summary

schwab-mcp is a Model Context Protocol (MCP) server that bridges Schwab brokerage accounts to LLM-based applications (such as Claude Desktop and claude.ai). It provides AI agents with real-time market data, account management, and **live trading capabilities**. Given that this system can execute real financial transactions, the security posture must be held to the highest standard.

Overall, the codebase demonstrates strong security awareness in several areas — file permissions for credentials (`0o600`), parameterized SQL queries, localhost-only OAuth callbacks, and a human-in-the-loop approval system for write operations. However, this review identified **4 high-severity**, **8 medium-severity**, and **5 low-severity** issues that should be addressed before production deployment.

---

## 1. Architecture & Communication Structure

### 1.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                        Deployment Modes                      │
│                                                              │
│  LOCAL MODE                    CLOUD RUN MODE                │
│  ┌──────────────────┐          ┌──────────────────────────┐  │
│  │ schwab-mcp       │          │ schwab-mcp remote-server │  │
│  │ server (stdio)   │          │ (HTTP + OAuth 2.1)       │  │
│  │                  │          │                          │  │
│  │ MCP over stdio   │          │ MCP over Streamable HTTP │  │
│  │ Token: local file│          │ Token: PostgreSQL        │  │
│  └──────┬───────────┘          └──────┬───────────────────┘  │
│         │                             │                      │
│         │                      ┌──────┴───────────────────┐  │
│         │                      │ schwab-mcp admin          │  │
│         │                      │ (Schwab OAuth re-auth UI) │  │
│         │                      │ Token: PostgreSQL          │  │
│         │                      └──────┬───────────────────┘  │
└─────────┼─────────────────────────────┼──────────────────────┘
          │                             │
          ▼                             ▼
┌──────────────────────────────────────────────────────────────┐
│                     External Services                         │
│                                                               │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ Schwab API      │  │ Discord API  │  │ Cloud SQL       │  │
│  │ (HTTPS)         │  │ (WebSocket)  │  │ (PostgreSQL)    │  │
│  │                 │  │              │  │                 │  │
│  │ Market data     │  │ Trade        │  │ Option chains   │  │
│  │ Account info    │  │ approval     │  │ Schwab tokens   │  │
│  │ Order execution │  │ workflow     │  │                 │  │
│  └─────────────────┘  └──────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 Communication Flows

| Flow | Protocol | Auth Mechanism | Encryption |
|------|----------|----------------|------------|
| MCP Client → MCP Server (local) | stdio | Process-level isolation | N/A (local IPC) |
| MCP Client → MCP Server (remote) | HTTPS (Streamable HTTP) | OAuth 2.1 Bearer Token | TLS (Cloud Run) |
| MCP Server → Schwab API | HTTPS | OAuth 2.0 (client credentials + tokens) | TLS |
| MCP Server → Discord | WSS | Bot token | TLS (discord.py) |
| MCP Server → Cloud SQL | Cloud SQL Connector | IAM + password auth | Cloud SQL Proxy encryption |
| Admin → Schwab OAuth | HTTPS | OAuth 2.0 browser flow | TLS |
| Admin → Cloud SQL | Cloud SQL Connector | IAM + password auth | Cloud SQL Proxy encryption |
| User Browser → Admin UI | HTTPS | Cloud Run IAM (`--no-allow-unauthenticated`) | TLS (Cloud Run) |
| User Browser → Consent Page | HTTPS | OAuth state parameter | TLS (Cloud Run) |

### 1.3 Data Classification

| Data Type | Sensitivity | Storage Location | At-Rest Protection |
|-----------|-------------|------------------|--------------------|
| Schwab Client ID/Secret | **Critical** | Env vars / credentials.yaml | File perms 0o600 / Secret Manager |
| Schwab OAuth Tokens | **Critical** | token.yaml / PostgreSQL | File perms 0o600 / DB access controls |
| MCP OAuth Tokens | High | In-memory only | Process isolation |
| Discord Bot Token | High | Env var only | Secret Manager |
| Account Numbers/Hashes | High | In-transit only | Not persisted |
| Market Data | Low | PostgreSQL (optional) | DB access controls |
| Order Details | **Critical** | In-transit only (logged briefly) | Not persisted |

---

## 2. Vulnerability Assessment

### 2.1 HIGH Severity

#### H1: Cross-Site Scripting (XSS) in Admin Error Page

**File:** `src/schwab_mcp/admin/app.py:222`
**CWE:** CWE-79 (Improper Neutralization of Input During Web Page Generation)

The Schwab OAuth callback error handler interpolates the exception message directly into HTML without escaping:

```python
return HTMLResponse(
    f"""...
    <h1 class="error">Authentication Failed</h1>
    <p>{str(e)}</p>    # ← Unescaped exception message
    ...""",
    status_code=500,
)
```

If the Schwab API returns an error containing HTML/JavaScript (or if an attacker crafts a malicious callback URL that triggers an exception with injected content), the script will execute in the authenticated admin's browser. Since the admin has access to initiate Schwab OAuth flows and write tokens to the database, this could lead to account takeover.

**Recommendation:** HTML-escape all dynamic content before embedding in HTML responses. Use `html.escape(str(e))` or a templating engine with auto-escaping.

---

#### H2: CSRF Protection Bypass via OAuth State Fallback

**File:** `src/schwab_mcp/admin/app.py:152-154`
**CWE:** CWE-352 (Cross-Site Request Forgery)

When the OAuth callback's `state` parameter doesn't match any stored state, the code falls back to using the most recent state entry:

```python
if state and state in _oauth_state:
    auth_context = _oauth_state.pop(state)["auth_context"]
elif _oauth_state:
    latest_key = max(_oauth_state.keys())
    auth_context = _oauth_state.pop(latest_key)["auth_context"]  # ← Fallback
```

This effectively defeats CSRF protection. An attacker who can deliver a crafted callback URL (with an arbitrary or missing `state` parameter) to the admin's browser can hijack any pending OAuth flow. The attacker could inject their own authorization code, causing the admin service to store the attacker's token — enabling the attacker to have their Schwab account's orders placed from this system, or potentially intercepting the legitimate user's token exchange.

**Recommendation:** Strictly reject callbacks with missing or non-matching state. Remove the fallback branch entirely.

---

#### H3: Unauthenticated Token Status Endpoint

**File:** `src/schwab_mcp/remote/app.py:203-230`
**CWE:** CWE-200 (Exposure of Sensitive Information)

The `/token-status` endpoint on the MCP server is accessible without any authentication and reveals sensitive token metadata:

```python
info = {
    "exists": True,
    "has_access_token": "access_token" in token,
    "has_refresh_token": "refresh_token" in token,
    "created_at": created.isoformat(),
    "age_days": round(age_days, 2),
    "refresh_likely_valid": age_days < 7,
}
```

This reveals whether the system has valid Schwab credentials, their age, and whether the refresh token is likely valid. An attacker could use this to time attacks when tokens are about to expire (when admin re-authentication is likely).

**Recommendation:** Place the `/token-status` endpoint behind authentication, or remove it from the public MCP service and keep it only on the admin service (which already requires IAM auth).

---

#### H4: `--jesus-take-the-wheel` Removes All Trading Safeguards

**Files:** `src/schwab_mcp/cli.py:379-381`, `src/schwab_mcp/remote/config.py:74-77`
**CWE:** CWE-862 (Missing Authorization)

This flag (also available as `JESUS_TAKE_THE_WHEEL=true` environment variable) completely bypasses the Discord approval workflow. When enabled, an LLM agent can execute **any trade** — market orders, option orders, bracket orders — with zero human oversight.

```python
if jesus_take_the_wheel:
    approval_manager = NoOpApprovalManager()
    allow_write = True
```

The flag name itself suggests it is not intended for production, but there is no runtime warning, no required confirmation, and no audit logging when trades are executed without approval. If this env var is accidentally set in a Cloud Run deployment, the LLM could autonomously drain a brokerage account.

**Recommendation:**
- Add prominent startup warnings when this flag is active (beyond the existing stderr note when combined with Discord)
- Log every write tool invocation with full parameters when approval is bypassed
- Consider requiring a second confirmation mechanism (e.g., a confirmation token) for Cloud Run deployments
- Add a guardrail for maximum order value when running without approvals

---

### 2.2 MEDIUM Severity

#### M1: Unbounded In-Memory OAuth State Growth

**Files:** `src/schwab_mcp/remote/oauth.py:67-71`, `src/schwab_mcp/admin/app.py:42`
**CWE:** CWE-770 (Allocation of Resources Without Limits)

The OAuth provider stores all client registrations, authorization codes, access tokens, refresh tokens, and state mappings in unbounded dictionaries:

```python
self._clients: dict[str, OAuthClientInformationFull] = {}
self._auth_codes: dict[str, AuthorizationCode] = {}
self._access_tokens: dict[str, AccessToken] = {}
self._refresh_tokens: dict[str, RefreshToken] = {}
self._state_mapping: dict[str, dict[str, str | None]] = {}
```

Similarly, the admin service's `_oauth_state` dict grows with each auth attempt. While expired tokens are cleaned up on access, there is no periodic cleanup or maximum size limit. An attacker sending many `/register` or `/authorize` requests could exhaust the server's memory.

**Recommendation:** Add maximum size limits to each dictionary and implement periodic cleanup of expired entries. For Cloud Run with max-instances=1, the 512Mi memory limit provides a natural cap, but explicit bounds would prevent degradation.

---

#### M2: No Rate Limiting on Any Endpoint

**Files:** `src/schwab_mcp/remote/app.py`, `src/schwab_mcp/admin/app.py`
**CWE:** CWE-770 (Allocation of Resources Without Limits)

No rate limiting exists on:
- OAuth registration (`/register`)
- Authorization (`/authorize`)
- Token exchange (`/token`)
- Consent page (`/consent`, `/consent/approve`)
- MCP tool calls (`/mcp`)
- Admin endpoints (`/`, `/schwab/auth`, `/datareceived`)

This makes the system vulnerable to brute-force attacks on authentication, denial of service, and excessive API calls to Schwab (which could trigger Schwab's own rate limits and lock the account).

**Recommendation:** Add rate limiting middleware (e.g., `slowapi` for Starlette or Cloud Run's built-in rate limiting). Critical: limit `/token`, `/register`, and `/mcp` endpoints.

---

#### M3: No OAuth Client Secret Validation

**File:** `src/schwab_mcp/remote/oauth.py:78-84`
**CWE:** CWE-287 (Improper Authentication)

The `SchwabMCPOAuthProvider` accepts the `mcp_oauth_secret` in its constructor but never validates it during client registration or token exchange:

```python
async def register_client(self, client_info: OAuthClientInformationFull) -> None:
    if not client_info.client_id:
        raise ValueError("No client_id provided")
    self._clients[client_info.client_id] = client_info  # ← No secret check
```

Any client that can reach the `/register` endpoint can register and subsequently obtain access tokens. The `mcp_oauth_client_secret` configuration value serves no security purpose.

**Recommendation:** Validate `client_secret` during dynamic client registration and during the token exchange flow. For the single-user Claude.ai use case, consider restricting registration to a pre-configured client ID.

---

#### M4: Credentials Directory Created Without Explicit Permissions

**File:** `src/schwab_mcp/tokens.py:127`
**CWE:** CWE-276 (Incorrect Default Permissions)

The `credentials_path()` function creates the data directory without explicit permissions, relying on the system umask:

```python
def credentials_path(app_name: str, filename: str = "credentials.yaml") -> str:
    data_dir = user_data_dir(app_name)
    pathlib.Path(data_dir).mkdir(parents=True, exist_ok=True)  # ← No mode=0o700
    return os.path.join(data_dir, filename)
```

Compare with `token_path()` which correctly sets `mode=0o700`:

```python
def token_path(app_name: str, filename: str = "token.yaml") -> str:
    data_dir = user_data_dir(app_name)
    pathlib.Path(data_dir).mkdir(mode=0o700, parents=True, exist_ok=True)  # ← Correct
```

On systems with a permissive umask (e.g., `0022`), the credentials directory could be world-readable, exposing `credentials.yaml` (which contains `client_id` and `client_secret`) to other users on the system.

**Recommendation:** Add `mode=0o700` to the `mkdir` call in `credentials_path()`, matching the pattern in `token_path()`.

---

#### M5: Exception Messages May Leak Sensitive Data

**Files:** `src/schwab_mcp/cli.py:163, 445`, `src/schwab_mcp/remote/app.py:230`
**CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)

Error messages from exceptions are displayed directly to users or returned in HTTP responses:

```python
# cli.py:163
click.echo(f"Error: {str(e)}", err=True)

# cli.py:445
send_error_response(f"Error running server: {str(e)}", ...)

# remote/app.py:230
return JSONResponse({"error": str(e)}, status_code=500)
```

Exception messages from `schwab-py`, `httpx`, or the database connector could contain URLs with tokens, connection strings with passwords, or other sensitive context.

**Recommendation:** Log full exceptions server-side but return generic error messages to clients. Replace `str(e)` in user-facing responses with sanitized error descriptions.

---

#### M6: Docker Containers Run as Root

**Files:** `Dockerfile.mcp`, `Dockerfile.admin`
**CWE:** CWE-250 (Execution with Unnecessary Privileges)

Neither Dockerfile creates a non-root user. The application runs as root inside the container:

```dockerfile
# No USER directive in either Dockerfile
ENTRYPOINT ["schwab-mcp"]
CMD ["remote-server"]
```

If a vulnerability allows code execution within the container, the attacker would have root privileges, potentially enabling container escape or lateral movement.

**Recommendation:** Add a non-root user to both Dockerfiles:
```dockerfile
RUN useradd -r -s /usr/sbin/nologin appuser
USER appuser
```

---

#### M7: SQL f-string Pattern in Stored Options Queries

**File:** `src/schwab_mcp/tools/stored_options.py:77-88`
**CWE:** CWE-89 (SQL Injection) — *Low actual risk, but risky pattern*

The query uses an f-string to interpolate the WHERE clause:

```python
where = " AND ".join(conditions)
rows = await ctx.db.execute(
    f"""
    SELECT ... FROM option_contracts oc
    JOIN option_chain_snapshots s ON s.id = oc.snapshot_id
    WHERE {where}
    ORDER BY ...
    LIMIT %s
    """,
    params,
)
```

While the current implementation is safe (all conditions are hardcoded strings with `%s` placeholders and all values are in `params`), this pattern is fragile. A future modification that accidentally interpolates user input into a condition string would create a SQL injection vulnerability.

**Recommendation:** Consider using a query builder or adding a comment marking this as a security-sensitive section. Add a unit test that verifies the `conditions` list never contains user-supplied data.

---

#### M8: Admin OAuth State Memory Leak

**File:** `src/schwab_mcp/admin/app.py:42, 124`
**CWE:** CWE-401 (Missing Release of Memory after Effective Lifetime)

The `_oauth_state` dictionary stores OAuth flow state but only cleans up entries on successful callback. If a user starts an OAuth flow but doesn't complete it (browser closes, navigates away), the state entry persists forever:

```python
_oauth_state: dict[str, Any] = {}  # ← Never cleaned except on callback
```

Over time (especially if re-authentication happens every 7 days with occasional failures), this could accumulate stale entries containing `auth_context` objects.

**Recommendation:** Add a TTL-based cleanup (e.g., discard entries older than 10 minutes) or limit the dictionary to a small number of entries (e.g., 5).

---

### 2.3 LOW Severity

#### L1: MCP Service Deployed with `--allow-unauthenticated`

**File:** `deploy.sh:83`

The MCP Cloud Run service is deployed with `--allow-unauthenticated`, making all routes publicly accessible. While the `/mcp` endpoint is protected by OAuth, the `/health`, `/token-status`, and OAuth discovery endpoints (`.well-known/oauth-authorization-server`) are fully public.

**Recommendation:** This is acceptable for the MCP protocol (Claude.ai needs to reach the discovery endpoints), but ensure no sensitive endpoints are added to the public routes without authentication.

---

#### L2: No Consent Form CSRF Token

**File:** `src/schwab_mcp/remote/oauth.py:160-162`

The consent form at `/consent/approve` uses the OAuth `state` parameter as its only CSRF defense:

```html
<form action="{self.server_url}/consent/approve" method="post">
    <input type="hidden" name="state" value="{state}">
```

The `state` value is a cryptographically random hex string, which provides adequate CSRF protection. However, since it's visible in the URL (the user navigates to `/consent?state=...`), it could be leaked via the Referer header if the consent page loads external resources.

**Recommendation:** The current implementation is acceptable given that the page loads no external resources. If external resources (analytics, fonts, CDN) are added in the future, add an independent CSRF token.

---

#### L3: SQL Semicolon-Based Statement Splitting

**File:** `src/schwab_mcp/db/_manager.py:102`

The `execute_script` method splits SQL on semicolons, which could fail if SQL strings contain semicolons:

```python
for statement in sql.split(";"):
    statement = statement.strip()
    if statement:
        cursor.execute(statement)
```

Currently only used for DDL (`CREATE TABLE`, `CREATE INDEX`), which don't contain semicolons in values. However, this is a fragile parsing approach.

**Recommendation:** Document that `execute_script` is DDL-only. Consider using pg8000's multi-statement support or a proper SQL parser if the scope expands.

---

#### L4: Self-Signed SSL Certificate for Localhost (Informational)

**File:** `src/schwab_mcp/auth.py:167-170`

The local OAuth callback server uses a self-signed SSL certificate with `verify=False`. This is intentional and properly scoped to `127.0.0.1` only (validated at `auth.py:114`). The SSL warnings are correctly suppressed.

**Status:** Acceptable — no action required.

---

#### L5: Callback URL Displayed in Full in CLI Output

**File:** `src/schwab_mcp/cli.py:107`

The full callback URL is displayed during auth setup. While this is needed for user verification, it could be captured in terminal logs or screen recordings.

**Recommendation:** Minor concern. Consider noting in documentation that terminal output during auth may contain sensitive URLs.

---

## 3. Positive Security Findings

The following security practices are well-implemented and should be maintained:

| Practice | Location | Assessment |
|----------|----------|------------|
| File permissions (0o600) for tokens and credentials | `tokens.py:61, 166` | **Strong** — atomic `os.open` with explicit mode |
| Callback URL restricted to 127.0.0.1 | `auth.py:114` | **Strong** — prevents SSRF-style attacks |
| Parameterized SQL queries throughout | `_manager.py`, `_ingestion.py`, `stored_options.py`, `token_storage.py` | **Strong** — no string interpolation of user data in SQL |
| Cryptographically secure token generation | `oauth.py:209, 245-246` via `secrets.token_hex` | **Strong** — proper entropy source |
| Discord approval workflow with authorized users | `discord.py:184` | **Strong** — whitelist-based approver verification |
| Secrets via Google Secret Manager | `deploy.sh:89, 147` | **Strong** — secrets never in env or config files |
| Token expiration and cleanup | `oauth.py:281-283, 296-298` | **Good** — expired tokens removed on access |
| Read/write tool separation | `tools/_registration.py:302-303` | **Good** — approval gating on write tools only |
| Minimal Discord intents | `discord.py:64-71` | **Good** — principle of least privilege |
| Client ID truncation in logs | `cli.py:106` | **Good** — partial masking of sensitive values |
| Cloud Run max-instances=1 | `deploy.sh:87` | **Good** — prevents token state synchronization issues |
| Admin service uses `--no-allow-unauthenticated` | `deploy.sh:141` | **Good** — IAM-gated access |
| YAML safe_load (not unsafe_load) | `tokens.py:101, 145` | **Good** — prevents YAML deserialization attacks |
| Token age enforcement (5-day max) | `auth.py:16`, `cli.py:350` | **Good** — forces periodic re-authentication |

---

## 4. Recommendations Summary

### Priority 1 — Fix Before Deployment

| ID | Issue | Fix |
|----|-------|-----|
| **H1** | XSS in admin error page | HTML-escape `str(e)` in `admin/app.py:222` |
| **H2** | OAuth state fallback bypasses CSRF | Remove fallback branch in `admin/app.py:152-154` |
| **H3** | Unauthenticated `/token-status` | Move behind auth or remove from public MCP service |
| **H4** | `--jesus-take-the-wheel` has no guardrails | Add audit logging, order value limits, startup warnings |
| **M4** | Credentials directory permissions | Add `mode=0o700` to `credentials_path()` |

### Priority 2 — Fix Before Production Scale

| ID | Issue | Fix |
|----|-------|-----|
| **M1** | Unbounded OAuth state dictionaries | Add max-size limits and periodic cleanup |
| **M2** | No rate limiting | Add rate limiting middleware |
| **M3** | No client secret validation in OAuth | Validate `client_secret` during registration and token exchange |
| **M5** | Exception messages leak data | Sanitize error messages in user-facing responses |
| **M6** | Containers run as root | Add `USER` directive to Dockerfiles |

### Priority 3 — Harden

| ID | Issue | Fix |
|----|-------|-----|
| **M7** | SQL f-string pattern | Add safety comments and tests |
| **M8** | Admin OAuth state memory leak | Add TTL-based cleanup |
| **L1-L5** | Various low-severity items | Address as part of routine maintenance |

---

## 5. Additional Deployment Recommendations

1. **Enable Cloud Run audit logging** to capture all HTTP requests to both services for forensic analysis
2. **Set up alerting** on Schwab API error rates — sudden spikes could indicate credential compromise
3. **Implement a maximum daily trade volume** guardrail, even with approval workflow enabled
4. **Add structured logging** with correlation IDs across MCP requests → Schwab API calls → Discord approvals
5. **Consider network egress restrictions** — the MCP server only needs to reach Schwab API, Discord API, and Cloud SQL; all other egress should be blocked
6. **Rotate the MCP OAuth secret** periodically — there is currently no rotation mechanism
7. **Add a `/revoke` endpoint** to the admin service to allow emergency token invalidation
8. **Pin dependency versions** in Dockerfiles — the `uv.lock` file helps, but ensure the lock is used during container builds
9. **Add security headers** to all HTML responses (Content-Security-Policy, X-Content-Type-Options, X-Frame-Options)

---

*End of security review report.*
