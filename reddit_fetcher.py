"""
Fetches new posts via Reddit's public .rss feeds — no API key, no OAuth app,
no approval wait. This works because Reddit's .rss endpoints were never part
of the priced/gated API surface; they're the same feeds RSS readers have used
for years and they still return live data with zero auth as of mid-2026.

Trade-offs vs the official API (accepted for a personal tool):
- RSS only gives you the post body as HTML-escaped summary text, not the raw
  markdown — fine for keyword filtering and LLM classification.
- No guaranteed rate-limit contract like OAuth has. We fetch politely (small
  delay between subreddits, identifiable User-Agent) to stay under the radar.
- If Reddit ever locks this down too, the only fallback is a paid third-party
  provider (Data365, Xpoz, etc.) — swap fetch_new_posts() to call whichever
  wrapper you want to pay for and nothing else in the pipeline changes.
"""
import time
import logging
import html
import re
from datetime import datetime, timezone

import feedparser
import requests

from config import REDDIT_RSS_USER_AGENT, SUBREDDITS, KEYWORDS, POST_LOOKBACK_LIMIT
from db import post_exists, insert_raw_post

logger = logging.getLogger("reddit_fetcher")

RSS_URL_TEMPLATE = "https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"

_TAG_RE = re.compile(r"<[^>]+>")


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


def passes_keyword_filter(title: str, body: str) -> bool:
    text = f"{title} {body}".lower()
    return any(kw in text for kw in KEYWORDS)


def fetch_new_posts() -> int:
    """
    Pull recent posts from all watched subreddits via RSS, apply a loose
    keyword pre-filter, and store new ones (unclassified) in Postgres.
    Returns count of new posts inserted.
    """
    inserted = 0
    headers = {"User-Agent": REDDIT_RSS_USER_AGENT}

    for sub_name in SUBREDDITS:
        url = RSS_URL_TEMPLATE.format(subreddit=sub_name, limit=POST_LOOKBACK_LIMIT)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                logger.warning(f"Rate limited on r/{sub_name}, skipping this run.")
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

                if not passes_keyword_filter(title, body):
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
                }
                insert_raw_post(post)
                inserted += 1

        except Exception as e:
            logger.error(f"Failed fetching r/{sub_name}: {e}")
            continue

        time.sleep(1)  # be polite between subreddit requests

    return inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = fetch_new_posts()
    print(f"Inserted {n} new candidate posts.")
