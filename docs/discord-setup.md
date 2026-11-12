# Discord Approval Setup

To use the account modification tools (placing orders, cancelling orders, etc.) safely, `schwab-mcp` can be configured to require approval via a Discord channel. This prevents an LLM from executing trades without your explicit confirmation.

## 1. Create a Discord Application

1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Click **New Application** and give it a name (e.g., "Schwab Approver").

## 2. Configure the Bot

1.  In the left sidebar, click **Bot**.
2.  Click **Reset Token** to generate a token. **Copy this token immediately**; you will need it for the `SCHWAB_MCP_DISCORD_TOKEN` configuration.
3.  Uncheck **Public Bot** (unless you really want others to add it, which is not recommended for this use case).
4.  Leave the privileged intents (Message Content, Server Members, Presence) off. The bot reads only emoji reactions on its own messages and needs none of them.

## 3. Invite the Bot to Your Server

1.  In the left sidebar, click **OAuth2** -> **URL Generator**.
2.  Under **Scopes**, check `bot`.
3.  Under **Bot Permissions**, check the following:
    *   **View Channels**
    *   **Send Messages**
    *   **Embed Links**
    *   **Add Reactions** (the bot adds ✅ and ❌ to each request)
    *   **Read Message History**
    *   **Manage Messages** (to remove stale approval requests)
4.  Copy the generated URL at the bottom.
5.  Open the URL in a browser and select the Discord server where you want to receive approval requests.

## 4. Create a Private Approval Channel

Approval requests show order details and the full account hash, and anyone who
can see the channel sees them. Create a dedicated text channel that only the
approvers and the bot can view: in the channel settings, under
**Permissions**, deny **View Channel** to `@everyone`, then allow it for each
approver and for the bot's role. Do not reuse a channel other people can read.

Only the configured approver IDs can approve or deny; reactions from anyone
else are removed and ignored.

## 5. Get the Channel ID

1.  In Discord, enable **Developer Mode** (User Settings -> Advanced -> Developer Mode).
2.  Right-click the text channel where you want the bot to post.
3.  Click **Copy Channel ID**. This is your `SCHWAB_MCP_DISCORD_CHANNEL_ID`.

## 6. Get Your User ID (Approver)

1.  Right-click your own username in Discord.
2.  Click **Copy User ID**. This is your `SCHWAB_MCP_DISCORD_APPROVERS` ID.

## Configuration

Set the bot token as an environment variable rather than a `--discord-token`
flag, which other local users can see in `ps` and which lands in shell history:

```bash
export SCHWAB_MCP_DISCORD_TOKEN="YOUR_BOT_TOKEN"
export SCHWAB_MCP_DISCORD_CHANNEL_ID="YOUR_CHANNEL_ID"
export SCHWAB_MCP_DISCORD_APPROVERS="YOUR_USER_ID"
uv run schwab-mcp server ...
```

The channel and approvers can also be passed as `--discord-channel-id` and
`--discord-approver` (repeat it for several reviewers).

## How approvals look

Each write request is posted as an embed with ✅ and ❌ reactions. React ✅ to
approve or ❌ to deny; with no decision before `--discord-timeout` (default
600 s) the request expires and is not executed. At most three requests can be
pending at once; further requests are refused until you answer.

The **Client ID (unverified)** field is whatever identifier the MCP client
sent. It is not authenticated, so do not rely on it to decide who is asking.

## Account names

Use the last four characters of `accountHash` returned by `get_accounts` as
the key for each name:

```bash
export SCHWAB_MCP_DISCORD_ACCOUNT_NAMES="A1B2=Example Brokerage,C3D4=Example Retirement"
```

You can also repeat `--discord-account-name "A1B2=Example Brokerage"`. CLI
entries override the environment variable. Commas separate entries; spaces in
names are preserved. The last entry for a suffix wins. Entries missing `=`, a
key, or a name are skipped with a warning; other entries are stored unchanged.
Keys are case-sensitive and must match the hash suffix exactly. Names set for
an inactive approval backend produce a startup warning.

Names appear in the Account field on pending and final messages. These are
locally configured names, keyed by hash suffix rather than account-number
suffix. Check for collisions; the full hash remains in Arguments for review.
No additional Schwab API calls are made.

When names are configured, an unmapped account shows
`…C3D4 (no configured name)`. Invalid hashes and names longer than 1024
characters after escaping receive no Account field. Length is checked when
rendering, without a warning.
With no names configured, the existing argument display is unchanged.
