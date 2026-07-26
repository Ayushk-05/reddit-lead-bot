"""
Fetches new posts via Reddit's public .rss feeds — no API key, no OAuth app,
no approval wait. This works because Reddit's .rss endpoints were never part
of the priced/gated API surface; they're the same feeds RSS readers have used
for years and they still return live data with zero auth as of mid-2026.

Trade-offs vs the official API (accepted for a personal tool):
- RSS only gives you the post body as HTML-escaped summary text, not the raw
  markdown — fine for keyword filtering and LLM classification.
- No guaranteed rate-limit contract like OAuth has. We fetch politely (delay
  between subreddits, shuffled order, identifiable User-Agent, retry-once on
  transient errors) to be a good citizen and reduce the chance of getting
  blocked, not because any of this is officially sanctioned.
- RSS isn't guaranteed to be complete — a very busy subreddit can push posts
  off the feed's limit between polls faster than a 10-min cron catches them.
  Fine at this scale (10 subs, 10-min interval); just don't assume it's a
  perfect record of everything posted.
- If Reddit ever locks this down too, the only fallback is a paid third-party
  provider (Data365, Xpoz, etc.) — swap fetch_new_posts() to call whichever
  wrapper you want to pay for and nothing else in the pipeline changes.
"""
import time
import random
import logging
import html
import re
from datetime import datetime, timezone

import feedparser
import requests

from config import (
    REDDIT_RSS_USER_AGENT, SUBREDDITS, KEYWORD_SCORES,
    KEYWORD_SCORE_THRESHOLD, POST_LOOKBACK_LIMIT, REDDIT_FETCH_DELAY,
)
from db import post_exists, insert_raw_post

logger = logging.getLogger("reddit_fetcher")

RSS_URL_TEMPLATE = "https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"

_TAG_RE = re.compile(r"<[^>]+>")
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


def _strip_html(raw_html: str) -> str:
    """RSS <summary> content is HTML. Strip tags and unescape entities to get
    plain text good enough for keyword filtering and the LLM prompt."""
    if not raw_html:
        return ""
    text = _TAG_RE.sub(" ", raw_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_post_id(entry) -> str:
    """entry.id looks like 't3_abc123' for Reddit's Atom feed — use as-is,
    it's already a stable unique key."""
    return entry.get("id", entry.get("link", ""))


def keyword_score(title: str, body: str) -> int:
    """Sum of weighted keyword hits. See KEYWORD_SCORES in config.py."""
    text = f"{title} {body}".lower()
    return sum(weight for kw, weight in KEYWORD_SCORES.items() if kw in text)


def passes_keyword_filter(title: str, body: str) -> bool:
    return keyword_score(title, body) >= KEYWORD_SCORE_THRESHOLD


class RedditRateLimited(Exception):
    """Raised on a 429 from Reddit's RSS. This is treated as IP-level
    throttling, not per-subreddit — fetch_new_posts stops the whole run
    on this rather than continuing to hit the remaining subreddits, which
    would just collect more 429s and prolong the block."""
    pass


def _fetch_rss(url: str, headers: dict, sub_name: str):
    """GET the RSS feed with one retry on transient server errors (5xx).
    Returns the response object, or None if the retry also failed.
    Raises RedditRateLimited on a 429 — not retried, not swallowed."""
    for attempt in (1, 2):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            if attempt == 1:
                logger.warning(f"Network error on r/{sub_name}, retrying in 2.5s: {e}")
                time.sleep(2.5)
                continue
            logger.error(f"Network error on r/{sub_name} after retry: {e}")
            return None

        if resp.status_code == 429:
            raise RedditRateLimited(sub_name)

        if resp.status_code in RETRYABLE_STATUS_CODES and attempt == 1:
            logger.warning(
                f"Got {resp.status_code} from r/{sub_name}, retrying in 2.5s."
            )
            time.sleep(2.5)
            continue

        return resp

    return None


def fetch_new_posts() -> int:
    """
    Pull recent posts from all watched subreddits via RSS, apply a loose
    keyword pre-filter, and store new ones (unclassified) in Postgres.
    Returns count of new posts inserted.
    """
    inserted = 0
    headers = {"User-Agent": REDDIT_RSS_USER_AGENT}

    # Shuffle order each run so the same subreddits don't always get hit
    # first/last — spreads requests around more naturally over time.
    subs = SUBREDDITS[:]
    random.shuffle(subs)

    for sub_name in subs:
        url = RSS_URL_TEMPLATE.format(subreddit=sub_name, limit=POST_LOOKBACK_LIMIT)
        try:
            try:
                resp = _fetch_rss(url, headers, sub_name)
            except RedditRateLimited:
                logger.warning(
                    f"Rate limited on r/{sub_name} — treating this as IP-level "
                    f"throttling and stopping the rest of this run's fetches "
                    f"rather than hitting {len(subs) - subs.index(sub_name) - 1} "
                    f"more subreddits into the same block. Will retry next run."
                )
                break

            if resp is None:
                continue
            resp.raise_for_status()

            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                logger.error(f"Failed parsing RSS for r/{sub_name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries:
                post_id = _extract_post_id(entry)
                if not post_id or post_exists(post_id):
                    continue

                title = entry.get("title", "")
                body = _strip_html(entry.get("summary", ""))

                score = keyword_score(title, body)
                if score < KEYWORD_SCORE_THRESHOLD:
                    continue

                author = entry.get("author", "unknown")
                if author.startswith("/u/"):
                    author = author[3:]

                published = entry.get("published_parsed") or entry.get("updated_parsed")
                created_utc = (
                    datetime(*published[:6], tzinfo=timezone.utc)
                    if published
                    else datetime.now(timezone.utc)
                )

                post = {
                    "id": post_id,
                    "subreddit": sub_name,
                    "title": title,
                    "body": body[:4000],
                    "url": entry.get("link", ""),
                    "author": author,
                    "created_utc": created_utc,
                    "keyword_score": score,
                }
                insert_raw_post(post)
                inserted += 1

        except Exception as e:
            logger.error(f"Failed fetching r/{sub_name}: {e}")

        finally:
            # Always pause between requests — including after a failure —
            # so a bad response doesn't turn into a zero-delay burst at
            # the remaining subreddits.
            time.sleep(REDDIT_FETCH_DELAY)

    return inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = fetch_new_posts()
    print(f"Inserted {n} new candidate posts.")