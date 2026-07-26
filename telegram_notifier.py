import json
import logging
import html
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("telegram_notifier")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _get_analysis(lead: dict) -> dict:
    a = lead["analysis"]
    return json.loads(a) if isinstance(a, str) else a


def esc(text):
    return html.escape(str(text or ""))


def format_lead_message(lead: dict) -> str:
    a = _get_analysis(lead)

    score = a.get("lead_score", 0)
    fire = "🔥" if score >= 8.5 else "✅" if score >= 6.5 else "👀"
    intent = a.get("intent", {})
    tag = "💡 Implicit lead" if intent.get("implicit") else "📌 Direct hire post"
    techs = ", ".join(a.get("technologies", [])) or "Unknown"
    reasoning = a.get("reasoning", [])

    msg = (
        f"{fire} <b>New Lead ({score:.1f}/10, fit {a.get('fit_score',0):.1f}/10)</b>\n\n"
        f"<b>Title:</b> {esc(lead['title'])}\n\n"
        f"<b>Subreddit:</b> r/{esc(lead['subreddit'])}\n"
        f"<b>Type:</b> {esc(tag)}\n"
        f"<b>Tech:</b> {esc(techs)}\n"
        f"<b>Budget:</b> {esc(str(a.get('budget', 'unknown')).title())}\n"
        f"<b>Urgency:</b> {esc(a.get('urgency', 0))}/10\n"
        f"<b>Likely to pay:</b> {'Yes' if a.get('likely_to_pay') else 'Unclear'}\n\n"
        f"<b>Summary:</b> {esc(a.get('summary', ''))}"
    )

    if reasoning:
        msg += "\n\n<b>Why:</b> " + esc("; ".join(reasoning[:3]))

    msg += f'\n\n<a href="{lead["url"]}">Open Reddit Post</a>'

    replies = a.get("reply_messages") or []
    if replies:
        msg += "\n\n<b>DM Drafts</b>"
        icons = {
            "friendly": "🙂",
            "technical": "🔧",
            "founder": "🤝",
        }

        for r in replies:
            msg += (
                f"\n\n<b>{icons.get(r.get('style'), '💬')} "
                f"{esc(r.get('style', '').title())}</b>\n"
                f"{esc(r.get('message', ''))}"
            )

    return msg


def send_lead_notification(lead: dict) -> bool:
    message = format_lead_message(lead)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(API_URL, json=payload, timeout=10)

        if not resp.ok:
            logger.error("Telegram response: %s", resp.text)

        resp.raise_for_status()

        logger.info("Telegram notification sent successfully.")
        return True

    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)

        if e.response is not None:
            logger.error("Telegram response body: %s", e.response.text)

        return False