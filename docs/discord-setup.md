# Discord Approval Setup

To use the account modification tools (placing orders, cancelling orders, etc.) safely, `schwab-mcp` can be configured to require approval via a Discord channel. This prevents an LLM from executing trades without your explicit confirmation.

## 1. Create a Discord Application

1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Click **New Application** and give it a name (e.g., "Schwab Approver").

## 2. Configure the Bot

1.  In the left sidebar, click **Bot**.
2.  Click **Reset Token** to generate a token. **Copy this token immediately**; you will need it for the `SCHWAB_MCP_DISCORD_TOKEN` configuration.
3.  Uncheck **Public Bot** (unless you really want others to add it, which is not recommended for this use case).
4.  (Optional) Enable "Message Content Intent" if you plan to use advanced features in the future, but it's not strictly required for button-based approvals.

## 3. Invite the Bot to Your Server

1.  In the left sidebar, click **OAuth2** -> **URL Generator**.
2.  Under **Scopes**, check `bot`.
3.  Under **Bot Permissions**, check the following:
    *   **View Channels**
    *   **Send Messages**
    *   **Embed Links**
    *   **Add Reactions** (if used)
    *   **Read Message History**
    *   **Manage Messages** (to remove stale approval requests)
4.  Copy the generated URL at the bottom.
5.  Open the URL in a browser and select the Discord server where you want to receive approval requests.

## 4. Get the Channel ID

1.  In Discord, enable **Developer Mode** (User Settings -> Advanced -> Developer Mode).
2.  Right-click the text channel where you want the bot to post.
3.  Click **Copy Channel ID**. This is your `SCHWAB_MCP_DISCORD_CHANNEL_ID`.

## 5. Get Your User ID (Approver)

1.  Right-click your own username in Discord.
2.  Click **Copy User ID**. This is your `SCHWAB_MCP_DISCORD_APPROVERS` ID.

## Configuration

Use these values when running the server:

```bash
uv run schwab-mcp server \
  --discord-token "YOUR_BOT_TOKEN" \
  --discord-channel-id "YOUR_CHANNEL_ID" \
  --discord-approver "YOUR_USER_ID" \
  ...
```

Or set them as environment variables:

```bash
export SCHWAB_MCP_DISCORD_TOKEN="YOUR_BOT_TOKEN"
export SCHWAB_MCP_DISCORD_CHANNEL_ID="YOUR_CHANNEL_ID"
export SCHWAB_MCP_DISCORD_APPROVERS="YOUR_USER_ID"
```

## Account names

Map the last four characters of an account hash to a name, as with Signal:

```bash
export SCHWAB_MCP_DISCORD_ACCOUNT_NAMES="A1B2=Example Brokerage,C3D4=Example Retirement"
```

You can also repeat `--discord-account-name "A1B2=Example Brokerage"`. CLI
entries override the environment variable. Commas separate entries; spaces in
names are preserved. The last entry for a suffix wins. Invalid or empty entries
are skipped with a warning.

Names appear in the Account field on pending and final messages. These are
locally configured names, keyed by hash suffix rather than account-number
suffix. Check for collisions; the full hash remains in Arguments for review.
No additional Schwab API calls are made.

Missing mappings, invalid hashes, or names longer than 1024 characters after
escaping leave the existing argument display unchanged.
