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

- `/generate package`: staff must choose **Vynex Tweaks**, **VYNEX Premium Package**, or **Vynex Overclock Bundle**. The private key unlocks only the selected app. The existing staff role and developer key work for all three choices.
- `/warn member reason`, `/warnings member`: moderators save and view warnings.
- `/timeout member minutes [reason]`, `/untimeout member`: manage timeouts.
- `/kick member [reason]`, `/ban member [reason]`, `/unban user_id`: membership moderation.
- `/clear amount`: delete up to 100 recent messages, including pinned messages.

Moderation checks the callerÃ¢â‚¬â„¢s permissions at runtime and enforces role hierarchy. All command replies are private. Kicks, bans, timeouts, and message cleanup include the moderator in DiscordÃ¢â‚¬â„¢s audit reason. Warnings stay in the local database; warning commands do not DM members. There is no automatic spam filter.

## Vynex integration

The bot calls `POST /v1/admin/generate-keys` using the existing `X-Admin-Password` and `X-Vynex-App: tweaks`, `premium`, or `overclock`, with `{ "count": 1 }`. The API stores the key in the selected app's separate access-key table. Accounts and access keys are separate between apps. The bot verifies the response's app header before displaying a key.

The deployed API blocks Vynex Tweaks personal license generation and resend via `/v1/auth/request-license`. Tweaks keys must be issued by staff. Premium emailed licenses remain available; verification and password-reset emails remain enabled for both apps.

After deploying this repository to Render, restart the bot with `python bot.py`. Startup syncs the updated command to `GUILD_ID`; the logs must show `Package selector version 2`. In Discord, `/generate` has a required `package` option with all three application names. Existing environment variables do not change.

The bot does not automatically retry key creation, because the endpoint has no idempotency support. If a request times out or delivery to Discord fails after the API saves a key, an unused key can remain on the server.

## Validation

Local checks cover slash command registration, request method/path/authentication, API response validation, and failure handling. No live keys or customer accounts were created during testing. Running the bot still requires your Discord token, server ID, and existing Vynex administrator password.

## Render web service startup

Keep the existing start command `python bot.py` and build command `pip install -r requirements.txt`. The bot now binds a small HTTP server to `0.0.0.0:$PORT` (default `10000`) before syncing Discord commands. This fixes Render's "No open ports detected" deployment timeout. No token or environment-variable changes are required.

Use `/health` as the Render health-check path. `/` also reports liveness. `/ready` returns 200 only while Discord is ready, otherwise 503. Responses contain no credentials or user data. Shutdown closes the HTTP listener along with the Discord client.

Deploy the latest commit and look for `Render health server listening on 0.0.0.0:` followed by the package-selector command-sync message. Music and Spotify commands have been removed.

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

The public dashboard is posted or refreshed automatically in channel `1562754545631887461`. Its persistent dropdown has exactly **About Vynex Tweaks** and **Rules**. Every selection opens a temporary, private panel for the selecting member, leaving the shared dashboard unchanged. About uses the supplied Vynex feature descriptions. Rules presents the latest supplied community and advertising rules with Previous/Next navigation. Support has moved to its own channel. Previously opened Assistance menus redirect members to the new Support Center. The public panel uses a Vynex banner, concise sections, a subtle divider, the persistent dropdown and a matching footer. The bot uploads the artwork as Discord attachments; no external image host is required. The dashboard works after a restart; `/dashboard` (Manage Server required) refreshes it manually without posting duplicates. The bot needs View Channel, Send Messages, Attach Files and Read Message History in the dashboard channel; everyone using the dashboard needs access to that channel.

## Staff event logs

Logs go to channel `1550300376853520434` using dark gray Components V2 containers with mentions disabled. Keep this channel restricted to trusted staff because key-generation logs contain the full license key, application, lifetime expiry, requesting staff member, channel and interaction ID. A failed log delivery does not generate another key; the requester receives the generated key plus a delivery warning, and Render receives an error containing no license key.

Successful bot moderation commands (warn, timeout, remove timeout, kick, ban, unban and clear) record the moderator and command arguments. Discord audit events also record external kicks, bans, unbans, timeout changes and moderator message deletions. Give the bot **View Audit Log** for external moderation events. Bot audit entries are skipped to avoid duplicating its command logs. Ordinary self-deletions do not identify a deleting actor in Discord's raw deletion event.

Single and bulk deleted-message events record channel/message IDs and cached author, text and attachment names. Uncached messages are explicitly marked unavailable; old deleted content cannot be fetched after deletion. Attachments are not downloaded by this logger. The logs channel itself is excluded from raw deletion logging to avoid feedback. Startup checks the log destination; `/logtest` (Manage Server required) sends a test message and reports delivery success. The bot needs **View Channel** and **Send Messages** in the logs channel.

## Community rules

The bot automatically posts or refreshes the complete community rules in text channel `1562749964017336391` on startup. Administrators or members with Manage Server can run `/rules` to refresh them manually. The latest supplied community rules, advertising policy, moderation policy and final notice are stored in `community_rules.txt`. The text is split into size-limited Components V2 messages with dark gray containers and no mentions. Existing bot-owned rule parts are edited on reconnect to avoid duplicate posts. The bot needs View Channel, Read Message History and Send Messages in the rules channel.

## Support Center and tickets

On startup, the bot posts or refreshes the Support Center in channel `1566855989578440804`. The dropdown has **Shop Support**, **General Support**, and **Partnership Support**. Members with Manage Server can run `/shop` to refresh it. Existing panel messages are reused. After the new panel is published successfully, the bot replaces its old ticket controls in `1542759018462715924` with a redirect and unpins them. Other messages are preserved; that channel now receives ban appeals.

Tickets are private text channels under category `1542810493792550962`. The opener, bot, administrators, and staff role `1542769771844599878` can access them. One active ticket per person per option is allowed. Persistent controls work after a restart, with ticket ownership retained in the channel topic. Old Buy Tweaks and Support tickets map to Shop Support and General Support, so they remain usable and prevent duplicate tickets in the corresponding category. Partnership tickets use the same privacy and transcript protections.

The owner, staff role `1542769771844599878`, or an administrator can select **Close Ticket**, then confirm. Conversation send permissions are frozen, attachments are copied to archive channel `1542810514617536533`, and complete HTML transcripts are posted there with links to the archived attachments. Long transcripts are split to fit Discord upload limits. Only after saving succeeds is the ticket channel deleted. If archiving fails, the channel is retained and its original send permissions are restored.

Required bot permissions: View Channels, Send Messages, Manage Channels, Read Message History, Attach Files, and Embed Links. Manage Messages is used to pin the panel. Ensure these permissions apply in the panel, ticket category and transcript channel. Keep the transcript channel restricted to trusted staff.

Enable **Message Content Intent** in Discord Developer Portal → Bot → Privileged Gateway Intents. The bot requests that intent so transcripts include message text. Existing `DISCORD_TOKEN`, `GUILD_ID`, `KEY_ROLE_ID`, API URL and developer key remain the same. Category `1542810493792550962` must be a category; the panel and transcript IDs must be text channels in the configured server.

The panel is posted automatically after a successful Render deployment. The HTTP port/health fix and all three app-specific key choices are preserved.

### Ticket mentions and neutral styling

New tickets notify only the opener and staff role `1542769771844599878` using explicit allowed-mention lists; everyone and other roles cannot be pinged by that message. Discord requires the staff role to be mentionable or the bot to have permission to mention non-mentionable roles for a notification to fire.

The community dashboard and Support Center use matching navy artwork and a slate accent (`#27364D`). Ticket controls, confirmations and archives retain a dark gray accent (`#2B2D31`). Buttons use Discord's neutral secondary style; Discord controls the container and button backgrounds. Existing open-ticket welcome/control messages are refreshed on bot startup without sending repeat pings.

## Overclock Bundle

The third product uses X-Vynex-App: overclock. Overclock accounts, sessions, codes, verification and reset records are separate from Tweaks and Premium. Use Discord /generate and choose Vynex Overclock Bundle, or select it in Vynex Developer 1.2. Existing Tweaks and Premium data is unchanged. Deploy the API before the bot/client update. No emailed self-service codes are enabled.

## Ban appeals

When someone is banned from the configured server, the bot attempts to DM a persistent **Submit a ban appeal** button. For `/ban`, it sends a conditional invitation immediately before applying the ban, while the member still shares the server. Bans performed elsewhere use Discord's ban event and a best-effort DM after the ban. Bot accounts are skipped. Closed DMs, blocks, or no shared server can prevent delivery; a failed or unconfirmed delivery is reported to the existing staff event log when possible. DM failure does not cancel a moderation action. No live bans are made during tests.

The questionnaire asks what happened, why the ban should be reconsidered, what the member would do differently, and optional additional information. Required answers are 10–1,000 characters; the optional answer is at most 1,000. Only the invited account can open and submit it, and the bot verifies that the account is currently banned before accepting an appeal. The invitation button still works after a bot restart; an already-open form may need to be reopened following a deploy.

Submissions include the Discord account, user ID, time and all answers in channel **`1542759018462715924`**, with mentions disabled. That channel's existing visibility is preserved; answers are visible to anyone who can read it. The form discloses the destination to the applicant. Submitting does not automatically unban anyone. Staff use their existing review process and `/unban` if they approve.

The bot requires View Channel, Send Messages, Embed Links and Read Message History in the appeals channel, plus Ban Members to verify eligibility. The moderation gateway intent is already enabled in code. Keep submitted appeal messages: their markers prevent duplicate submissions across restarts, including retries after an uncertain send result. Only one appeal is accepted per invitation period; a later ban receives a new invitation. No questionnaire text is written to application logs or local storage.

`/health` identifies this release as `support-appeals-v1`, includes the Render commit, and reports startup checks for the support panel, ban appeals and dashboard. A false feature flag identifies a channel/permission refresh failure; `/ready` separately reports Discord connectivity.

## Ticket claims and panel artwork

Every new and existing ticket receives a **Claim Ticket** button next to **Close Ticket**. Only the configured support role or an administrator can claim a ticket. The card identifies the assigned staff member, and the button becomes **Release Claim**. Only that staff member or an administrator can release the assignment. Claiming does not change channel access or the ticket owner's ability to close it.

Claims are stored in the channel topic and recovered after restarts. Simultaneous claims are serialized in the running bot; the second staff member is told who already owns it. Claim changes also share the transcript/close lock. Old tickets without a claim continue to work. The topic remains the durable record if an edit to the card fails; `/shop` refreshes ticket controls and recovers the displayed assignment. Run one active bot instance to avoid concurrent topic writes from independent processes.

The public panels use the committed `assets/vynex-community.png`, `assets/vynex-support.png` and `assets/vynex-footer.png`. These are reattached when existing panels are refreshed, so expired Discord attachment links are not reused. The bot needs Attach Files in both public panel channels. Existing bot-owned messages are edited; startup refresh does not ping members. The artwork renderer in `tools/render_panel_assets.cjs` is a development tool only, using `@napi-rs/canvas`; Node is not required to run the bot. Discord controls the final card width, text sizes and background theme.
