# Premium Discord bot

Python 3.10 or newer. Private purple Premium key embeds inspired by your screenshot.
The bot requests real lifetime access keys from https://vynex-api.onrender.com. Customers activate them in Vynex Tweaks after signing in and verifying their email.

## Setup

1. Create an application and bot at https://discord.com/developers/applications and copy its bot token.
2. Copy `.env.example` to `.env`. Enter the token and your server ID. Enable Developer Mode in Discord to copy IDs.
3. The service URL is already set. Set `VYNEX_ADMIN_PASSWORD` to the existing value in your Vynex API Render environment. Enter it locally in `.env`; do not send it in chat. Customize `COMPANY_NAME` if desired. Set `KEY_ROLE_ID` to the staff role allowed to issue keys; `0` allows only administrators. Give this role only to trusted staff.
4. Invite the bot using the `bot` and `applications.commands` scopes. Give it View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Moderate Members, Kick Members, Ban Members, and View Audit Log. Place its role above members it will moderate. Enable Message Content Intent for transcripts and deleted-message text. Administrator permission is not required.
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

## Public community dashboard

The public dashboard is posted or refreshed automatically in channel `1562754545631887461`. Its persistent dropdown has exactly **About Vynex Tweaks**, **Rules**, and **Assistance**. Every selection opens a temporary, private panel for the selecting member, leaving the shared dashboard unchanged. About uses the supplied Vynex feature descriptions. Rules presents the latest supplied community and advertising rules with Previous/Next navigation. Assistance displays the complete existing purchase/support panel and its **Buy Tweaks / Support** dropdown, opening tickets through the same private ticket system, staff permissions, pings and transcript archive. All panels retain dark gray Components V2 containers. The dashboard works after a restart; `/dashboard` (Manage Server required) refreshes it manually without posting duplicates. The bot needs View Channel, Send Messages and Read Message History in the dashboard channel; everyone using the dashboard needs access to that channel.

## Staff event logs

Logs go to channel `1550300376853520434` using dark gray Components V2 containers with mentions disabled. Keep this channel restricted to trusted staff because key-generation logs contain the full license key, application, lifetime expiry, requesting staff member, channel and interaction ID. A failed log delivery does not generate another key; the requester receives the generated key plus a delivery warning, and Render receives an error containing no license key.

Successful bot moderation commands (warn, timeout, remove timeout, kick, ban, unban and clear) record the moderator and command arguments. Discord audit events also record external kicks, bans, unbans, timeout changes and moderator message deletions. Give the bot **View Audit Log** for external moderation events. Bot audit entries are skipped to avoid duplicating its command logs. Ordinary self-deletions do not identify a deleting actor in Discord's raw deletion event.

Single and bulk deleted-message events record channel/message IDs and cached author, text and attachment names. Uncached messages are explicitly marked unavailable; old deleted content cannot be fetched after deletion. Attachments are not downloaded by this logger. The logs channel itself is excluded from raw deletion logging to avoid feedback. Startup checks the log destination; `/logtest` (Manage Server required) sends a test message and reports delivery success. The bot needs **View Channel** and **Send Messages** in the logs channel.

## Community rules

The bot automatically posts or refreshes the complete community rules in text channel `1562749964017336391` on startup. Administrators or members with Manage Server can run `/rules` to refresh them manually. The latest supplied community rules, advertising policy, moderation policy and final notice are stored in `community_rules.txt`. The text is split into size-limited Components V2 messages with dark gray containers and no mentions. Existing bot-owned rule parts are edited on reconnect to avoid duplicate posts. The bot needs View Channel, Read Message History and Send Messages in the rules channel.

## Components V2 shop and tickets

On startup, the bot posts or refreshes a Components V2 panel in channel `1542759018462715924`, using the supplied Vynex purchase description. The dropdown has **Buy Tweaks** and **Support**. Administrators can run `/shop` to refresh the panel. Pinned panel messages are reused, so reconnects and redeploys do not create duplicate panels.

Tickets are private text channels under category `1542810493792550962`. The opener, bot, administrators, and staff role `1542769771844599878` can access them. One active ticket per person per option is allowed. Persistent controls work after a restart, with ticket ownership retained in the channel topic.

The owner, staff role `1542769771844599878`, or an administrator can select **Close Ticket**, then confirm. Conversation send permissions are frozen, attachments are copied to archive channel `1542810514617536533`, and complete HTML transcripts are posted there with links to the archived attachments. Long transcripts are split to fit Discord upload limits. Only after saving succeeds is the ticket channel deleted. If archiving fails, the channel is retained and its original send permissions are restored.

Required bot permissions: View Channels, Send Messages, Manage Channels, Read Message History, Attach Files, and Embed Links. Manage Messages is used to pin the panel. Ensure these permissions apply in the panel, ticket category and transcript channel. Keep the transcript channel restricted to trusted staff.

Enable **Message Content Intent** in Discord Developer Portal → Bot → Privileged Gateway Intents. The bot requests that intent so transcripts include message text. Existing `DISCORD_TOKEN`, `GUILD_ID`, `KEY_ROLE_ID`, API URL and developer key remain the same. Category `1542810493792550962` must be a category; the other two IDs must be text channels in the configured server.

The panel is posted automatically after a successful Render deployment. The HTTP port/health fix and both app-specific key choices are preserved.

### Ticket mentions and neutral styling

New tickets notify only the opener and staff role `1542769771844599878` using explicit allowed-mention lists; everyone and other roles cannot be pinged by that message. Discord requires the staff role to be mentionable or the bot to have permission to mention non-mentionable roles for a notification to fire.

Ticket panels, welcome messages, confirmations and archives retain boxed Components V2 containers with a dark gray accent (`#2B2D31`). Buttons use Discord's neutral secondary style; Discord controls the container and button backgrounds. Existing open-ticket welcome/control messages are refreshed on bot startup without sending repeat pings.
