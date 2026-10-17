# NCR job alerts — daily local bot

The bot posts **clearly labeled sample jobs** with `/jobs preview`. It collects real jobs once daily at **6 PM Asia/Manila** and shares that collection across configured servers. `/jobs fetch` uses only still-permitted cached results; it never starts another provider request. The Philippine Jooble adapter remains disabled until a Philippine API key and explicit Discord republication permission are configured. No other provider has a usable listing adapter yet. If all providers are unavailable, the bot stays online and reports the problem. Sample URLs use `example.com` and do not accept applications. Each listing has its own **View / Apply** link. Eligible listings need an identified NCR workplace or base, an HTTP(S) job/application URL, a disclosed positive base salary, and no confirmed closure or elapsed expiry.

The bot ranks comparable **PHP monthly base salary lower bounds** first. Annual pay is divided by 12. Daily pay needs explicit days per month; hourly pay needs explicit hours per month or both hours per day and days per month. Bonuses are shown separately. Missing, negotiable-only, zero, invalid, and commission-only salaries are excluded. Disclosed positive base pay with an unknown period is shown as stated after comparable salaries. It sends at most 15 new listings in **one compact embed per server per day**. Each numbered entry has title, employer, NCR location, known employment type, base salary, source, and its own clickable application link. Work arrangement appears only when reliable source data says On-site, Hybrid, or Remote. Long optional text is shortened; the bot includes fewer jobs when an embed limit would be reached. All included jobs are recorded after the single message succeeds. Stable IDs and canonical URLs prevent repeat delivery per server.

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
3. Ask Jooble how long API results may be retained in memory. Only after Jooble approves Discord use, put the key in your private `.env` as `JOOBLE_PH_API_KEY`, set `JOOBLE_DISCORD_APPROVED=true`, and set `JOOBLE_CACHE_SECONDS` no higher than the permitted duration (a nonnegative number of seconds). The default 0 retains no results for a later manual command. The daily schedule does not grant 24-hour cache retention. Set `JOOBLE_KEYWORDS` to a search term you want (for example `engineer`). One daily collection makes one Jooble API request for the first 50 Metro Manila results; the bot filters the returned locations and ranks eligible results before posting up to 15. It does not visit or scrape job webpages.

Jooble's documented result supplies a job link, which the card uses for **View / Apply**. It does not supply an employer-direct application URL, expiry date, or closure status, so the bot cannot independently verify that every indexed job is still open. Review the first real batch manually. Unstated salary periods remain unranked; the bot does not guess monthly pay. Jooble's API also does not supply work arrangement, so the arrangement is omitted. Results are cached only in the running process for the configured permitted duration; the delivery database stores identifiers, URL hashes, and Discord message IDs, not full provider results.

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

The bot creates its server settings, delivery, daily collection, daily batch, and local source-usage tables on startup. An existing first-milestone delivery table gets an additive URL-hash column and index. The account needs permission to create tables, alter the delivery table, and read/write rows in this database. Use a URL encoded password in `DATABASE_URL` if it contains characters such as `@`, `:`, or `/`.

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

Leave the terminal open. In your server, run `/jobs setup channel` and select a text channel. The bot checks permissions, sends a test message, and saves the channel. Then run `/jobs preview`. It posts one clearly labeled sample batch in salary order. Run preview again to see duplicate skipping. At 6 PM Philippine time, the bot collects once and posts at most one real batch per configured server. `/jobs fetch` can post still-permitted cached results, if present. With no approved provider, it reports **sources unavailable**. All three commands require server Administrator permission. For another sample demo in the same server, use a new local database or delete sample delivery rows from PostgreSQL.

The daily collection claim is saved before calling providers. A restart after 6 PM catches up only if the date was not already claimed, preventing a second request that day. If the bot crashes after a claim but before posting, it waits until the next day; unposted results cannot be recovered after their permitted cache retention expires. A successful Discord send followed by a database failure can leave an unrecorded message; inspect the channel before retrying in that rare case. A successful search with no eligible jobs with disclosed salaries is reported separately from **sources unavailable**. With no approved provider, the scheduler makes no live request and posts no real jobs.

With `DISCORD_TEST_GUILD_ID`, commands are synced to that test server. Without it, they are registered globally and can take longer to appear. If you change between those modes, old Discord command registrations may linger until Discord refreshes them.

## Project layout and next milestones

- `job_alert_bot/jobs.py`: source-independent job and salary models, eligibility, ranking.
- `job_alert_bot/sources.py`: `JobSource` interface and fictional sample adapter.
- `job_alert_bot/delivery.py`: Compact 15-entry batch embed and post-send delivery recording.
- `job_alert_bot/daily.py`: 6 PM Philippine-time cycle and persisted daily claim.
- `job_alert_bot/database.py`: SQLAlchemy PostgreSQL tables for server channels and deliveries.
- `job_alert_bot/jooble.py`: permission-gated Philippine Jooble REST adapter.
- `job_alert_bot/collection.py`: shared collection, permitted in-memory caching, source status, and cross-source deduplication.
- `job_alert_bot/source_errors.py`: quota, authentication, and temporary failure categories.
- `job_alert_bot/bot.py`: administrator-only slash commands.

Railway deployment remains a later milestone. This version needs a running local process at 6 PM Philippine time. Permitted cached results are in memory and lost on restart.
