import json
import logging
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("telegram_notifier")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _get_analysis(lead: dict) -> dict:
    """psycopg2 returns JSONB as a dict already in most setups, but handle
    the str case too in case the driver/config returns raw text."""
    a = lead["analysis"]
    return json.loads(a) if isinstance(a, str) else a


def format_lead_message(lead: dict) -> str:
    a = _get_analysis(lead)

    score = a.get("lead_score", 0)
    fire = "🔥" if score >= 8.5 else "✅" if score >= 6.5 else "👀"
    intent = a.get("intent", {})
    tag = "💡 Implicit lead" if intent.get("implicit") else "📌 Direct hire post"
    techs = ", ".join(a.get("technologies", [])) or "Unknown"
    reasoning = a.get("reasoning", [])

    msg = (
        f"{fire} *New Lead ({score:.1f}/10, fit {a.get('fit_score', 0):.1f}/10)*\n\n"
        f"*Title:* {lead['title']}\n\n"
        f"*Subreddit:* r/{lead['subreddit']}\n"
        f"*Type:* {tag}\n"
        f"*Tech:* {techs}\n"
        f"*Budget:* {a.get('budget', 'unknown').title()}\n"
        f"*Urgency:* {a.get('urgency', 0)}/10\n"
        f"*Likely to pay:* {'Yes' if a.get('likely_to_pay') else 'Unclear'}\n\n"
        f"*Summary:* {a.get('summary', '')}\n"
    )

    if reasoning:
        msg += "\n*Why:* " + "; ".join(reasoning[:3])

    msg += f"\n\n[Open post]({lead['url']})"

    # DM drafts — review, edit, copy into Reddit DM yourself. Never sent automatically.
    replies = a.get("reply_messages") or []
    if replies:
        msg += "\n\n— — — DM drafts (review before sending) — — —"
        icons = {"friendly": "🙂", "technical": "🔧", "founder": "🤝"}
        for r in replies:
            icon = icons.get(r.get("style"), "💬")
            msg += f"\n\n*{icon} {r.get('style', '').title()}:*\n{r.get('message', '')}"

    return msg


def send_lead_notification(lead: dict) -> bool:
    message = format_lead_message(lead)
    try:
        resp = requests.post(
            API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed for post {lead.get('id')}: {e}")
        return False
