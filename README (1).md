# Reddit Lead Scanner → Telegram

Personal-use pipeline. No auth, no UI, no users table. Just:

```
cron (every 10 min) → Reddit RSS (newest 8/subreddit, shuffled order)
                                                        │
                                                        ▼
                                    weighted keyword score ≥ threshold?
                                                        │
                                                       yes
                                                        │
                                                        ▼
                                    top MAX_GEMINI_CALLS candidates by score
                                                        │
                                                        ▼
                                    ONE Gemini call per candidate:
                                    qualify + score + draft outreach
                                    (retries on transient errors, hard stop on quota)
                                                        │
                                                        ▼
                                    Postgres (analysis JSONB) → Telegram
                                                        │
                                                        ▼
                                    You review, edit, copy into Reddit DM yourself
```

Two things keep this within Gemini rate/quota limits, not one:
1. **The keyword filter is a real gate, not a courtesy filter.** Weighted scoring
   (`KEYWORD_SCORES` in `config.py`) — a single explicit hiring phrase clears the
   threshold alone, implicit-only posts need several signals to co-occur. A typical
   fetch of ~80-100 raw posts across 10 subreddits should whittle down to roughly
   10-20 that clear the bar.
2. **A hard cap (`MAX_GEMINI_CALLS`) on top of that.** Even if more candidates clear
   the keyword threshold than expected, only the highest-scoring N get analyzed per
   run — the rest wait for next run rather than burning quota indiscriminately. And
   if Gemini returns 429 (quota exhausted) mid-run, the loop stops immediately
   instead of cycling through guaranteed failures for every remaining candidate —
   see `ai_classifier.QuotaExhausted`.

**Nothing is ever sent to Reddit automatically.** The single Gemini call in
`ai_classifier.py` qualifies the lead AND drafts 3 outreach variants (friendly /
technical / founder) in the same pass — it works out an outreach strategy first,
then writes the messages from that strategy, which reads more natural than asking
for the message directly. Drafts land in your Telegram message; you copy, tweak,
and send manually.

**No Reddit API key required.** Reddit closed self-service OAuth app registration
in late 2025 (new keys now need manual approval, 2-4 week wait). This project
sidesteps that entirely by reading Reddit's public `.rss` feeds instead — every
subreddit has one at `reddit.com/r/{sub}/new/.rss`, no auth needed, and it
survived the 2023 API lockdown because it was never part of the priced API
surface. `reddit_fetcher.py` handles this; you don't need to do anything Reddit-side.

## Setup (~10 min)

1. **Gemini API key**: go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
   sign in with the Google account that has your **AI Pro/Ultra subscription**, generate a key.
   Signing in with that account is what matters — the key automatically inherits your
   subscription's higher rate limits and Gemini Pro model access, no separate billing setup.

2. **Telegram bot**: message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
   Then message [@userinfobot](https://t.me/userinfobot) to get your own chat_id.

3. **Postgres**: any instance works (local, Supabase, Railway, Neon free tier is fine for this volume).
   ```bash
   psql $DATABASE_URL -f schema.sql
   ```

4. **Env**:
   ```bash
   cp .env.example .env
   # fill in GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DATABASE_URL
   # REDDIT_RSS_USER_AGENT is optional but set it to something identifiable
   ```

5. **Install & test**:
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python main.py
   ```

6. **Cron** (every 10 min):
   ```bash
   crontab -e
   ```
   Add:
   ```
   */10 * * * * cd /full/path/to/reddit-lead-bot && /full/path/to/venv/bin/python main.py >> logs/run.log 2>&1
   ```

## Before running

Edit `DEVELOPER_PROFILE` in `config.py` with your real skills/portfolio. This is the
only thing standing between the outreach drafts and the model inventing experience
you don't have — keep it factual and specific, including a line about what you're
*not* claiming (e.g. no prior freelance clients yet). The prompt in `ai_classifier.py`
is instructed to stay within this profile, but the profile is only as good as what
you put in it.

## How the single call works

`ai_classifier.analyze_post()` sends one request per candidate post using Gemini's
native JSON mode (`response_mime_type="application/json"`), which constrains the
output to valid JSON at the API level rather than just asking nicely in the prompt.
It gets back: `should_notify`, `lead_score`, `fit_score`, `confidence`, `intent`
(explicit/implicit), `urgency`, `budget`, `likely_to_pay`, `technologies`, `category`,
`reasoning`, `summary`, `outreach_strategy`, and `reply_messages` (3 variants). If
`should_notify` is false, the model skips drafting outreach entirely — no wasted
generation on posts that aren't worth pursuing. The full JSON is stored as-is in
Postgres (`analysis` JSONB column) so you can query on any field later without a
schema migration — e.g. `SELECT * FROM posts WHERE analysis->>'category' = 'Backend Development'`.

## Tuning

- `MIN_SCORE_TO_NOTIFY` in `.env` — raise it if you're getting noise, lower it if you're missing leads.
- `KEYWORD_SCORE_THRESHOLD` in `.env` (default 15) — the real lever on how many posts reach
  Gemini at all. Raise it to send fewer, higher-confidence posts; lower it if good leads are
  getting filtered out before they ever reach Gemini. Check the logs — "Fetched N new
  candidate posts" tells you how many cleared this bar on a given run.
- `MAX_GEMINI_CALLS` in `.env` (default 15) — hard cap on Gemini calls per run, independent
  of the keyword filter. Candidates are ranked by keyword score first, so if more posts clear
  the threshold than this cap allows, the strongest ones get analyzed this run and the rest
  wait for the next one (they don't get skipped forever). This is what actually prevents a
  87-candidates-in-one-run situation from happening again.
- `KEYWORD_SCORES` in `config.py` — weighted with real spread (15/8/6/4/2 tiers, not 3/2/1).
  A single explicit hiring phrase clears the threshold alone; implicit pain-point language
  needs several signals to co-occur in the same post. Add/reweight terms here if you notice
  a pattern of leads you're catching or missing — e.g. add terms specific to your own stack
  the way `trading bot` / `fastapi` are weighted higher here as profile-relevant signals.
- `SUBREDDITS` in `config.py` — add/remove freely.
- `POST_LOOKBACK_LIMIT` in `.env` (default 8) — newest N posts fetched per subreddit per run,
  not a backlog scan. Raise it if you're running cron less often than every ~10 min and want
  to make sure busy subreddits don't outpace it.
- `GEMINI_RATE_LIMIT_DELAY` in `.env` — spacing (seconds) between analysis calls. Google AI Pro
  limits are well above the plain free tier's ~10 RPM, so 1.5s is a conservative default. If
  you see 429s in the logs, raise it; if you never do, feel free to lower it further.

## Migrating an existing database

If you set up Postgres before this update, the `posts` table is missing the
`keyword_score` column used for ranking candidates. Run this once:

```sql
ALTER TABLE posts ADD COLUMN IF NOT EXISTS keyword_score INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_posts_keyword_score ON posts (keyword_score DESC);
```

(Also included at the bottom of `schema.sql` for reference — or just re-run
`python init_db.py` against a fresh database.)

## Cost

Covered by your existing Google AI Pro subscription — the API key generated from that account
draws on your subscription's included usage rather than a separate pay-per-call bill. Using
`gemini-2.5-pro` (set as the default model) costs more per call than the free-tier Flash models
would, but at 10 subreddits polled every 10 min this is a light workload relative to what Pro
includes. Watch the logs for 429s if you ever scale up subreddit count significantly — that's
the signal to either raise `GEMINI_RATE_LIMIT_DELAY` or drop to `gemini-2.5-flash` for the
high-volume classification pass.

## Known corners cut (on purpose, since it's just for you)

- No retry queue for failed Telegram sends beyond the next cron run picking it back up
  (posts stay `notified = false` until a send succeeds).
- No pagination/backfill — `POST_LOOKBACK_LIMIT` just grabs the most recent N posts per
  subreddit each run. Fine at 10-min intervals; if you ever go longer between runs, bump it up.
- Single Telegram chat, single filter profile. If you ever want a second persona
  duplicate the config rather than parameterizing it — not worth the abstraction for one user.
- RSS gives post body as HTML-escaped summary text, not raw markdown — fine for
  keyword filtering and the LLM prompt, but don't expect perfectly clean formatting
  if you ever print `body` directly.
- No official rate-limit contract on RSS like OAuth has. The fetcher waits 1s
  between subreddits and backs off on HTTP 429; if Reddit tightens this further,
  the fallback is a paid third-party provider — swap `fetch_new_posts()` in
  `reddit_fetcher.py` and nothing else in the pipeline needs to change.
