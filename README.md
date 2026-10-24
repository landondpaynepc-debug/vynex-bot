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

## Voice music

`/joinvc` joins the requesting member's voice channel self-deafened without starting a track. `/leave` stops music, cancels pending playback, clears the queue and disconnects. Both require the member to be in the same voice channel when the bot is connected. The `/music` slash command has been removed; use the VC chat buttons for playback controls.

If Discord returns HTTP 429 for an interaction acknowledgement, the bot pauses further music response requests for the server's Retry-After interval (at least 60 seconds) and still attempts the requested voice action. This avoids preventing Leave/Stop just because Discord refused the text response. Cloudflare 1015 is a Discord-side rate limit; code cannot remove it, and repeated command attempts can prolong it. Logs contain the status rather than dumping the HTML error page.

The bot posts a reusable dark gray Components V2 control panel directly in the voice channel's text chat, with **Pause, Resume, Skip, Queue, Stop, Leave** buttons. Join the same voice channel to use them; The `/music` command is removed. The bot needs Send Messages in that voice channel's chat. Public controls persist across restarts, but playback queues do not. Music commands immediately send a status card rather than leaving a thinking indicator; controls do not wait for the track-loading lock. Stop cancels pending play requests. Before reporting Now Playing, the bot verifies an actual first Opus audio packet and preserves it for playback. Empty or blocked audio streams produce an explicit error, and server-muted bots are detected.

Join a normal voice channel and use `/play query:song name and artist` or a public `https://soundcloud.com/artist/track` link. Playback searches up to five SoundCloud results and skips unavailable or preview-only results. The bot joins self-deafened and plays for everyone in the voice channel. YouTube and Spotify audio links are not used by `/play`; `/spotify` remains available for personal Spotify device controls.

The VC chat panel provides Pause, Resume, Skip, Show queue, Stop and Leave. Controls require the member to be in the same voice channel as the bot. Connect and Speak permissions are required. Queues support up to 50 pending tracks, reject live streams and tracks longer than two hours, and exist only while the process runs. The bot disconnects after three idle minutes. Responses and now-playing messages use dark gray Components V2.

The Render build remains `pip install -r requirements.txt`. Voice dependencies provide PyNaCl, DAVE and FFmpeg; yt-dlp resolves SoundCloud audio. Private, protected and subscription-only recordings cannot play. The host must support outbound Discord voice UDP. Live Discord audio must be verified by a member in voice after deployment.

## Reviews and giveaways

`/review stars:5 text:Your review package:Vynex Tweaks` posts a public Components V2 review in the current channel. Any server member can use it, with a five-minute cooldown. Ratings are constrained to 1–5, displayed with filled/empty stars, the username and user ID, review text and selected app (Tweaks by default; Premium is also available). User mentions in reviews cannot ping anyone.

`/giveaway prize:Premium access duration:2h text:Your custom announcement` is restricted to members with Manage Server. It posts a public dark gray Components V2 card in the current channel with an Enter Giveaway button, host, entry count and Discord end-time timestamps. Durations accept `m`, `h`, or `d`, from 1 minute to 30 days. One entry per server member; bot accounts and late entries are rejected. The scheduler checks every 15 seconds and selects one random entrant, displays the winner's username/mention and disables entry when it ends. A giveaway with no entries ends without a winner.

Giveaway recovery records and entry lists are stored as JSON attachments on bot-owned messages in staff logs channel `1550300376853520434`. Give the bot View Channel, Read Message History, Send Messages and Attach Files there, and keep these records intact. They survive Render restarts and deployments without relying on Render's temporary disk. On recovery, overdue giveaways finish; a saved winner is never redrawn after an announcement retry. The bot must be running to announce results. Members can keep using entry buttons after a restart. The giveaway channel needs View Channel, Send Messages and Read Message History for the bot.

## Welcome messages and shared styling

New joins automatically receive role `1542769773882908743` in the configured server. Give the bot **Manage Roles** and place its highest role above this role. The role must not be managed by an integration. Startup validates this configuration. Existing member roles are preserved; a role-assignment failure is logged and does not prevent the welcome message. Welcome previews do not assign roles, and existing members are not backfilled on restart.

New member joins in the configured server post a dark gray Components V2 welcome card to channel `1542758858886225930`. The card shows the member's avatar, current server member count, a welcome mention and a short welcome notice. It has no channel-list section. Only the joining member can be pinged. `/welcometest` (Manage Server required) posts a preview using the requesting member. The bot requires View Channel and Send Messages in the welcome channel.

**Before deploying this version, enable Server Members Intent in Discord Developer Portal → Bot → Privileged Gateway Intents.** The code requests the members intent so Discord sends join events. Keep Message Content Intent enabled for transcripts and deleted-message logs. No existing members are welcomed again on restart.

Key-generation cards, warnings, command replies and ticket/dashboard notices also use dark gray Components V2 containers. Long text responses split to fit Discord's limit; key responses stay private. This replaces the remaining legacy embeds.

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


## Link a personal Spotify account

Giveaway entry buttons reload missing recovery records after rolling deployments. An orphaned, bot-owned active panel with zero entries can recreate its record on the next entry without changing its deadline. Panels showing existing entries are never reset; missing records are reported as unavailable rather than falsely ended. Keep giveaway recovery attachments in the staff logs channel.


`/spotify action:Link account` opens a private Components V2 panel with a Spotify sign-in button. After Spotify consent, use Now playing, Devices, Resume, Pause, Next, Previous, Select device, or Unlink account. The panel includes private playback buttons. Each command uses only the invoking member's Discord ID; another member cannot use that member's panel. Commands control playback on the member's own Spotify devices and do not broadcast Spotify audio into voice.

The public Vynex API must deploy `spotify_account.py` and configure `SPOTIFY_CLIENT_ID`. Register `https://vynex-api.onrender.com/spotify/callback` as the app's redirect URI. PKCE is used, so no client secret is needed. Bot environment settings remain the existing API URL and administrator password. Spotify Premium and a permitted Developer app are required; development-mode apps currently permit up to five authorized users. Open Spotify on a phone or computer and start a track before using playback controls. A missing Client ID reports incomplete setup rather than pretending the account is linked.
