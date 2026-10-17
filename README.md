# NCR job alerts — manual local bot

The bot posts **clearly labeled sample jobs** with `/jobs preview`. `/jobs fetch` collects real results only from enabled, approved providers. The Philippine Jooble adapter is implemented but remains disabled until a Philippine API key and explicit Discord republication permission are configured. No other provider has a usable listing adapter yet. If all providers are unavailable, the bot stays online and says so. There is no automatic scheduler. Sample URLs use `example.com` and do not accept applications. Each card has its own **View / Apply** link. Eligible listings need an identified NCR workplace or base, an HTTP(S) job/application URL, and no confirmed closure or elapsed expiry. A remote job is not automatically NCR eligible.

The bot ranks comparable **PHP monthly base salary lower bounds** first. Annual base pay is divided by 12. Daily pay needs explicit days per month; hourly pay needs explicit hours per month or both hours per day and days per month. Bonuses are shown separately. Unknown or non-comparable pay goes last. It sends at most 15 new listings per command and records each successful job message separately for each server. Stable provider IDs prevent same-source repeats; canonical listing URLs prevent cross-source repeats when both providers point to the same URL. It does not merge merely similar titles or employers, so separate vacancies remain separate.

The collection service isolates provider errors. It distinguishes explicit quota exhaustion, access/authentication failures, temporary errors (including HTTP 429 with `Retry-After`), and successful empty searches. Limited coverage, including disabled providers, is reported as partial coverage; complete collection failure says **sources unavailable**, never “no new jobs.” Jooble has no documented quota-exhaustion response shape, so an opaque HTTP 403 is reported as access/authentication failure; only an explicit quota message is classified as exhausted. This bot reserves at most 500 Jooble requests per key in PostgreSQL, using a key hash rather than storing the key. Jooble may count requests made elsewhere, so its actual remaining allowance can be lower.

## Provider status and access requirements

| Provider | Current status | Official access findings | What to obtain before an adapter can run |
| --- | --- | --- | --- |
| Jooble Philippines | Awaiting key and approval; adapter implemented | [PH API registration](https://ph.jooble.org/api/about), [REST documentation](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation), [site terms](https://ph.jooble.org/info/terms). The free key has a **500-request lifetime** quota. The terms restrict republication without express permission. | PH-domain API key, written permission for attributed Discord cards, and an allowed in-memory retention period. |
| JobStreet/SEEK | Unavailable for this use; no listing adapter | [SEEK API](https://developer.seek.com/) requires approval and documents recruitment-software workflows such as posting and applications, not a public search feed for Discord alerts. Its [rate limits](https://developer.seek.com/graphql/error-responses) vary by operation and are mostly undisclosed. | Ask SEEK through its integration request for an approved job-listing feed covering PH, Discord reuse rights, rate limits, and retention. A partner credential alone does not establish those rights. |
| Indeed Philippines | Unavailable for this use; no listing adapter | [Indeed's API guides](https://docs.indeed.com/api-guides/) focus on employer/ATS operations, not a public job-search feed. Its [terms](https://ph.indeed.com/legal?hl=en_PH) restrict automated site access without written permission; API limits may vary, and some sponsored services may incur charges. | Ask Indeed for an approved listing-search/feed product, PH coverage, Discord reuse permission, limits and retention. No paid service will be enabled without your authorization. |
| PhilJobNet | Unavailable for this use; no listing adapter | The [official portal](https://philjobnet.gov.ph/) supports browsing, but I found no published public job-feed API, request limit, or automated reuse grant. Its [contact page/privacy policy](https://philjobnet.gov.ph/privacy.aspx) lists `support@philjobnet.gov.ph`. | Ask the Bureau of Local Employment for a documented job feed/API, Discord reuse permission, request limits, and retention rules. |
| Kalibrr | Unavailable for this use; no listing adapter | Its [help center](https://kalibrr-support.zendesk.com/hc/en-us/articles/21664815834905-Do-Kalibrr-offer-integration-with-other-platforms) says the API integration is for customers displaying **their own** Kalibrr jobs on a career website. It gives no public cross-employer feed or limit for this use. | Ask an account manager whether a licensed PH job feed and Discord redistribution rights exist, with limits and retention. |

No undocumented endpoint, webpage scraper, or sample-data fallback is used by `/jobs fetch`. There is no working fallback provider yet; Jooble quota exhaustion will be reported while the other providers remain disabled.

## Jooble access and permission

The [Philippine Jooble API registration page](https://ph.jooble.org/api/about) requires a request for a key. [Jooble's REST API documentation](https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation) says country-specific keys are required, documents the request and response fields, and states a **500-request lifetime limit** on the free key. Its [connection guide](https://help.jooble.org/en/support/solutions/articles/60000922689-how-to-connect-to-the-jooble-rest-api-after-receiving-the-key) says API calls must comply with API terms. The [Philippine site terms](https://ph.jooble.org/info/terms) restrict copying content for republication without express written permission. The API page describes displaying results on a website, but does not clearly cover posting cards in a Discord server.

Before enabling `/jobs fetch`:

1. Request a **Philippine-domain** API key at [ph.jooble.org/api/about](https://ph.jooble.org/api/about). A key from `jooble.org` is for the US market and will not work for Philippine listings.
2. Ask Jooble via the API request/support channel, or `compliance@jooble.com` listed in its terms, for written confirmation that your bot may post brief job cards to your Discord server(s). Describe the fields: job title, company, location, stated salary, Jooble attribution, and an individual link to the Jooble posting. Ask whether this use is permitted under your API key, and retain their response.
3. Ask Jooble how long API results may be retained in memory. Only after Jooble approves Discord use, put the key in your private `.env` as `JOOBLE_PH_API_KEY`, set `JOOBLE_DISCORD_APPROVED=true`, and set `JOOBLE_CACHE_SECONDS` no higher than the permitted duration (0–3600 seconds). The default 0 retains no results between sequential requests. Concurrent server commands still share one in-flight fetch. Set `JOOBLE_KEYWORDS` to a search term you want (for example `engineer`). One live collection makes one Jooble API request for the first 50 Metro Manila results; the bot filters the returned locations and ranks eligible results before posting up to 15. It does not visit or scrape job webpages.

Jooble's documented result supplies a job link, which the card uses for **View / Apply**. It does not supply an employer-direct application URL, expiry date, or closure status, so the bot cannot independently verify that every indexed job is still open. Review the first real batch manually. Unstated salary periods remain unranked; the bot does not guess monthly pay. Jooble's API also does not supply work arrangement, so cards say “Not specified.” Results are cached only in the running process for the configured permitted duration; the delivery database stores identifiers, URL hashes, and Discord message IDs, not full provider results.

## 1. Create and invite a Discord bot

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application, open **Bot**, create or reset its token, and copy it. Treat the token like a password.
2. Under **Installation** (or **OAuth2 → URL Generator**), select the `bot` and `applications.commands` scopes. Give the bot **View Channels**, **Send Messages**, and **Embed Links** permissions. Invite it to a server you administer. The chosen alert channel must allow all three permissions for the bot.
3. In Discord, enable **Developer Mode** under Advanced settings, then right click your test server and copy its ID. This is optional but makes slash commands appear quickly in that test server. You do not need Message Content intent.

## 2. Prepare PostgreSQL

Install and start PostgreSQL locally. In `psql` as a PostgreSQL administrator, run the following, replacing the example password:

```sql
CREATE USER jobbot WITH PASSWORD 'choose_a_strong_local_password';
CREATE DATABASE jobbot OWNER jobbot;
```

The bot creates its server settings, delivery, and local source-usage tables on startup. An existing first-milestone delivery table gets an additive URL-hash column and index. The account needs permission to create tables, alter the delivery table, and read/write rows in this database. Use a URL encoded password in `DATABASE_URL` if it contains characters such as `@`, `:`, or `/`.

## 3. Configure and run on Windows PowerShell

From this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Open `.env` and replace the token and database password. Optionally set `DISCORD_TEST_GUILD_ID` to your server ID. Leave Jooble approval false until you have the key and permission above. The other four providers have no configuration keys because there is no approved adapter for them. `.env` is ignored by Git. Never put a real token, API key, or password in `.env.example` or a commit.

Then run:

```powershell
python -m pytest -q
ncr-job-bot
```

Leave the terminal open. In your server, run `/jobs setup channel` and select a text channel. The bot checks its channel permissions, sends a test message, and saves that channel. Then run `/jobs preview`. It posts four sample cards in salary order. Run preview again to see duplicate skipping. `/jobs fetch` reports **sources unavailable** until an approved real provider is configured. After Jooble access is configured, run `/jobs fetch` and inspect the real cards. All three commands require server Administrator permission. For another sample demo in the same server, use a new local database or delete the sample delivery rows from PostgreSQL; changing the alert channel alone does not reset deliveries.

With `DISCORD_TEST_GUILD_ID`, commands are synced to that test server. Without it, they are registered globally and can take longer to appear. If you change between those modes, old Discord command registrations may linger until Discord refreshes them.

## Project layout and next milestones

- `job_alert_bot/jobs.py`: source-independent job and salary models, eligibility, ranking.
- `job_alert_bot/sources.py`: `JobSource` interface and fictional sample adapter.
- `job_alert_bot/delivery.py`: Discord card creation, 15-job cap, and immediate per-message delivery recording.
- `job_alert_bot/database.py`: SQLAlchemy PostgreSQL tables for server channels and deliveries.
- `job_alert_bot/jooble.py`: permission-gated Philippine Jooble REST adapter.
- `job_alert_bot/collection.py`: shared collection, permitted in-memory caching, source status, and cross-source deduplication.
- `job_alert_bot/source_errors.py`: quota, authentication, and temporary failure categories.
- `job_alert_bot/bot.py`: administrator-only slash commands.

Automatic 00:00/06:00/12:00/18:00 Asia/Manila scheduling and Railway deployment remain later milestones. This version needs a running local process and an administrator to invoke preview or fetch manually.
