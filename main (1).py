"""
Entry point for the cron job. Runs the full pipeline once and exits:

RSS -> already analyzed? skip -> weighted keyword score -> below threshold? skip
     -> top MAX_GEMINI_CALLS candidates by keyword_score
     -> Gemini (analyze + draft, retry/backoff on transient errors, hard stop on quota)
     -> DB (scored) -> above MIN_SCORE_TO_NOTIFY? -> Telegram

Two things keep this within rate/quota limits:
1. Only posts clearing the keyword score threshold ever reach Gemini
   (config.KEYWORD_SCORES) — this is the main volume cut.
2. Even among those, only the top MAX_GEMINI_CALLS by keyword_score get
   analyzed per run — the rest wait for next run rather than getting
   skipped forever (see db.get_unanalyzed_posts, sorted by keyword_score).

Schedule this with cron every 10 min, e.g.:
    */10 * * * * cd /path/to/reddit-lead-bot && /path/to/venv/bin/python main.py >> logs/run.log 2>&1
"""
import logging
import time

from config import MIN_SCORE_TO_NOTIFY, GEMINI_RATE_LIMIT_DELAY, MAX_GEMINI_CALLS
from reddit_fetcher import fetch_new_posts
from ai_classifier import analyze_post, QuotaExhausted
from telegram_notifier import send_lead_notification
from db import get_unanalyzed_posts, save_analysis, get_leads_to_notify, mark_notified

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def run():
    start = time.time()

    # 1. Fetch new posts from Reddit via RSS, already-seen posts are skipped
    #    at the DB level (post_exists check), and only posts clearing the
    #    weighted keyword score threshold get inserted at all — see
    #    reddit_fetcher.passes_keyword_filter / config.KEYWORD_SCORES.
    new_count = fetch_new_posts()
    logger.info(f"Fetched {new_count} new candidate posts from Reddit (post keyword filter).")

    # 2. Analyze the strongest unanalyzed candidates, capped at MAX_GEMINI_CALLS.
    #    get_unanalyzed_posts sorts by keyword_score descending, so if there's
    #    a backlog bigger than budget, the most promising posts get the calls.
    candidates = get_unanalyzed_posts(limit=MAX_GEMINI_CALLS)
    logger.info(
        f"Analyzing {len(candidates)} candidate posts "
        f"(cap: {MAX_GEMINI_CALLS}, top score: {candidates[0]['keyword_score'] if candidates else 0})."
    )
    for i, post in enumerate(candidates):
        try:
            analysis = analyze_post(post)
            save_analysis(post["id"], analysis)
        except QuotaExhausted as e:
            remaining = len(candidates) - i
            logger.warning(
                f"Gemini quota exhausted after {i} calls this run. "
                f"Stopping analysis — {remaining} candidates left unanalyzed, "
                f"will be re-ranked and retried next run. ({e})"
            )
            break
        if i < len(candidates) - 1:
            time.sleep(GEMINI_RATE_LIMIT_DELAY)

    # 3. Notify on anything that qualifies and hasn't been notified yet
    leads = get_leads_to_notify(MIN_SCORE_TO_NOTIFY)
    logger.info(f"{len(leads)} leads ready to notify.")
    for lead in leads:
        ok = send_lead_notification(lead)
        if ok:
            mark_notified(lead["id"])

    logger.info(f"Run complete in {time.time() - start:.1f}s.")


if __name__ == "__main__":
    run()
