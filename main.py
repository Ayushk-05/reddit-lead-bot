"""
Entry point for the cron job. Runs the full pipeline once and exits:

Reddit -> keyword filter -> DB (raw) -> AI analyze+draft (1 call) -> DB (scored) -> Telegram

Schedule this with cron every 10 min, e.g.:
    */10 * * * * cd /path/to/reddit-lead-bot && /path/to/venv/bin/python main.py >> logs/run.log 2>&1
"""
import logging
import time

from config import MIN_SCORE_TO_NOTIFY, GEMINI_RATE_LIMIT_DELAY
from reddit_fetcher import fetch_new_posts
from ai_classifier import analyze_post
from telegram_notifier import send_lead_notification
from db import get_unanalyzed_posts, save_analysis, get_leads_to_notify, mark_notified

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def run():
    start = time.time()

    # 1. Fetch new posts from Reddit
    new_count = fetch_new_posts()
    logger.info(f"Fetched {new_count} new candidate posts from Reddit.")

    # 2. Analyze anything unanalyzed — one Gemini call per post does both
    #    qualification AND outreach drafting (see ai_classifier.py).
    #    Gemini's free tier is rate-limited (~10 req/min), so we space calls
    #    out rather than firing them back-to-back.
    unanalyzed = get_unanalyzed_posts()
    logger.info(f"Analyzing {len(unanalyzed)} posts.")
    for i, post in enumerate(unanalyzed):
        analysis = analyze_post(post)
        save_analysis(post["id"], analysis)
        if i < len(unanalyzed) - 1:
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
