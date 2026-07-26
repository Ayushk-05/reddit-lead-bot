# Reddit Lead Scanner → Telegram

Personal-use pipeline. No auth, no UI, no users table. Just:

```
cron (every 10 min) → Reddit RSS feeds (.rss, no API key) → keyword filter → Postgres (raw)
                                                        │
                                                        ▼
                                    ONE Gemini call per post:
                                    qualify + score + draft outreach
                                                        │
                                                        ▼
                                    Postgres (analysis JSONB) → Telegram
                                                        │
                                                        ▼
                                    You review, edit, copy into Reddit DM yourself
```

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
   sign in with any Google account, generate a key. No credit card, no waitlist, no approval
   wait — this is what solves the "can't get an API key" problem from Reddit.

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
- `KEYWORDS` in `config.py` — cheap pre-filter to avoid burning an API call on every single post.
  Keep it loose. The real judgment call is the AI's job, not the keyword list's.
- `SUBREDDITS` in `config.py` — add/remove freely.
- `GEMINI_RATE_LIMIT_DELAY` in `.env` — spacing (seconds) between analysis calls. Free tier caps
  at ~10 requests/minute; the default 6.5s keeps you under that. Lower it if you upgrade to a
  paid Gemini tier later.

## Cost

Free, as long as you stay on Gemini's free tier (Gemini 2.5 Flash: ~10 requests/min, 1,500/day
as of mid-2026 — plenty for 10 subreddits polled every 10 min). No credit card attached, so
there's no risk of an unexpected bill; you'll just start seeing 429 errors in the logs if you
somehow exceed the daily quota, and the next cron run picks up where it left off.

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
