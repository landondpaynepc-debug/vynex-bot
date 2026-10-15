# Premium Discord bot

Python 3.10 or newer. Private purple Premium key embeds inspired by your screenshot.
The bot requests real lifetime access keys from https://vynex-api.onrender.com. Customers activate them in Vynex Tweaks after signing in and verifying their email.

## Setup

1. Create an application and bot at https://discord.com/developers/applications and copy its bot token.
2. Copy `.env.example` to `.env`. Enter the token and your server ID. Enable Developer Mode in Discord to copy IDs.
3. The service URL is already set. Set `VYNEX_ADMIN_PASSWORD` to the existing value in your Vynex API Render environment. Enter it locally in `.env`; do not send it in chat. Customize `COMPANY_NAME` if desired. Set `KEY_ROLE_ID` to the staff role allowed to issue keys; `0` allows only administrators. Give this role only to trusted staff.
4. Invite the bot using the `bot` and `applications.commands` scopes. Give it View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Moderate Members, Kick Members, and Ban Members. Place its role above members it will moderate. It does not need Administrator or privileged intents.
5. Open a terminal in this folder and run:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python bot.py
```

Keep the program running for the bot to remain online. Commands sync to the configured server at startup.
Never share the token or `.env`. Back up `bot.sqlite3`, which stores moderation warnings. License records stay in your Vynex PostgreSQL database.

## Commands

- `/generate package`: staff must choose **Vynex Tweaks** or **VYNEX Premium Package**. The private key unlocks only the selected app. The existing staff role and developer key work for both choices.
- `/warn member reason`, `/warnings member`: moderators save and view warnings.
- `/timeout member minutes [reason]`, `/untimeout member`: manage timeouts.
- `/kick member [reason]`, `/ban member [reason]`, `/unban user_id`: membership moderation.
- `/clear amount`: delete up to 100 recent messages, including pinned messages.

Moderation checks the callerÃ¢â‚¬â„¢s permissions at runtime and enforces role hierarchy. All command replies are private. Kicks, bans, timeouts, and message cleanup include the moderator in DiscordÃ¢â‚¬â„¢s audit reason. Warnings stay in the local database; warning commands do not DM members. There is no automatic spam filter.

## Vynex integration

The bot calls `POST /v1/admin/generate-keys` using the existing `X-Admin-Password` and `X-Vynex-App: tweaks` or `premium`, with `{ "count": 1 }`. The API stores the key in the selected app's separate access-key table. Accounts and access keys are separate between apps. The bot verifies the response's app header before displaying a key.

The deployed API blocks Vynex Tweaks personal license generation and resend via `/v1/auth/request-license`. Tweaks keys must be issued by staff. Premium emailed licenses remain available; verification and password-reset emails remain enabled for both apps.

After deploying this repository to Render, restart the bot with `python bot.py`. Startup syncs the updated command to `GUILD_ID`; the logs must show `Package selector version 1`. In Discord, `/generate` has a required `package` option with both application names. Existing environment variables do not change.

The bot does not automatically retry key creation, because the endpoint has no idempotency support. If a request times out or delivery to Discord fails after the API saves a key, an unused key can remain on the server.

## Validation

Local checks cover slash command registration, request method/path/authentication, API response validation, and failure handling. No live keys or customer accounts were created during testing. Running the bot still requires your Discord token, server ID, and existing Vynex administrator password.

## Render web service startup

Keep the existing start command `python bot.py` and build command `pip install -r requirements.txt`. The bot now binds a small HTTP server to `0.0.0.0:$PORT` (default `10000`) before syncing Discord commands. This fixes Render's "No open ports detected" deployment timeout. No token or environment-variable changes are required.

Use `/health` as the Render health-check path. `/` also reports liveness. `/ready` returns 200 only while Discord is ready, otherwise 503. Responses contain no credentials or user data. Shutdown closes the HTTP listener along with the Discord client.

Deploy the latest commit and look for `Render health server listening on 0.0.0.0:` followed by the package-selector command-sync message. Voice-support warnings about PyNaCl or davey are unrelated to this bot's key and moderation commands.
