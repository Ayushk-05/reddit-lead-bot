import os
from dotenv import load_dotenv

load_dotenv()

# No Reddit API key needed — RSS feeds require no auth. Reddit does check the
# User-Agent header on requests though, so use something identifiable rather
# than the default requests UA (which gets blocked more often).
REDDIT_RSS_USER_AGENT = os.environ.get(
    "REDDIT_RSS_USER_AGENT", "personal-lead-scanner/1.0 (by u/your_username_here)"
)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# With a Google AI Pro/Ultra subscription linked to the account that generated
# this key, you get access to Pro models and higher rate limits — default to
# gemini-2.5-pro for better classification/outreach quality. If you're on the
# plain free tier instead, set this to gemini-2.5-flash in .env.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
# Google AI Pro raises your rate limit well above the free tier's ~10 RPM, so
# this can drop a lot. 1.5s is a conservative buffer, not a hard requirement —
# lower it further if you're not seeing 429s in the logs.
GEMINI_RATE_LIMIT_DELAY = float(os.environ.get("GEMINI_RATE_LIMIT_DELAY", 1.5))

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DATABASE_URL = os.environ["DATABASE_URL"]

MIN_SCORE_TO_NOTIFY = float(os.environ.get("MIN_SCORE_TO_NOTIFY", 6.5))
# Newest N posts per subreddit per run, not a general backlog scan. At a
# 10-min cron interval this is plenty to catch new posts without re-scanning
# a wide window every time — the DB dedup (analysis IS NULL) handles the rest.
POST_LOOKBACK_LIMIT = int(os.environ.get("POST_LOOKBACK_LIMIT", 8))
# A post needs to clear this weighted keyword score before it's worth a
# Gemini call. See KEYWORD_SCORES below for how the score is built. With the
# current weights, a single strong explicit-hire match (15) clears this alone;
# implicit-only posts need several weak signals stacked together to get here.
KEYWORD_SCORE_THRESHOLD = int(os.environ.get("KEYWORD_SCORE_THRESHOLD", 15))
# Hard cap on Gemini calls per run, regardless of how many posts clear the
# keyword threshold. This is the real backstop against quota exhaustion —
# candidates are sorted by keyword_score descending first (db.get_unanalyzed_posts),
# so if there are more candidates than budget, the strongest ones get analyzed
# and the rest wait for next run rather than getting skipped permanently.
MAX_GEMINI_CALLS = int(os.environ.get("MAX_GEMINI_CALLS", 15))

# --- Fill this in once with your real background. ---
# This gets fed to the DM generator so it never invents experience you don't have.
# Keep it factual and specific — vague filler just produces vague DMs.
DEVELOPER_PROFILE = """
Backend/full-stack developer. Core stack: Python (FastAPI), Node.js/Express, PostgreSQL, Next.js, React.
Recent work: built a real-time trading terminal (PySide6, WebSockets, ccxt) with live exchange data
and SMC-based signal analysis; built a multi-exchange trade-copying system with idempotent order
handling, rate limiting, and Prometheus metrics; currently interning on an AI-powered BI platform
(FastAPI, Next.js, PostgreSQL, LangChain, Docker).
Comfortable with: REST API design, WebSockets, Docker, async Python, SQL schema design, deployment
to AWS/Render/Railway.
NOT claiming: enterprise-scale production experience, specific frameworks/languages not listed above,
prior freelance client history (this is early freelance/contract work).
"""

SUBREDDITS = [
    "forhire",
    "freelance",
    "slavelabour",
    "startups",
    "SaaS",
    "Entrepreneur",
    "webdev",
    "node",
    "reactjs",
    "smallbusiness",
]

# Weighted pre-filter — this is the actual gatekeeper on Gemini quota, not a
# courtesy filter. Tiers are spread wide on purpose (15/8/6/4/2, not 3/2/1) so
# there's a real gap between "this alone is a lead" and "this needs company."
#
#   Tier 1 (15): explicit hiring/founder-role language — ONE match clears the
#                threshold by itself, no other signal needed.
#   Tier 2 (8):  budget/payment language — strong on its own, but usually
#                appears in the same post as something from a lower tier too.
#   Tier 3 (6):  strong project-type or profile-specific signals (MVP, the
#                developer's actual stack/domain — trading bots, FastAPI).
#   Tier 4 (4):  general tech/domain terms — common enough that they need to
#                co-occur with something else to add up to real signal.
#   Tier 5 (2):  implicit pain-point language — needs several of these
#                stacked together (roughly 8 co-occurring) to clear threshold
#                on implicit signal alone, which is the right bar: a single
#                "deadline" or "bug" mention proves nothing by itself.
#
# Tune KEYWORD_SCORE_THRESHOLD above if this is letting through too many/few.
KEYWORD_SCORES = {
    # Tier 1 — explicit hiring/founder-role language
    "hire": 15, "hiring": 15, "looking for a dev": 15, "looking for a developer": 15,
    "need a developer": 15, "need a dev": 15, "developer needed": 15,
    "looking to hire": 15, "technical cofounder": 15, "co-founder": 15,
    "founding engineer": 15, "freelancer": 15, "contractor": 15, "hire you": 15,
    "looking for a": 15, "need a": 8,  # broader phrase fragments, catches
                                          # "looking for a Node.js developer" etc
                                          # where the exact tier-1 phrase doesn't
                                          # match due to a tech name in between

    # Tier 2 — budget/payment language
    "budget": 8, "paid": 8, "pay you": 8, "willing to pay": 8, "compensation": 8,

    # Tier 3 — strong project-type / profile-specific signals
    "mvp": 6, "build my": 6, "build a": 6, "trading bot": 6, "fastapi": 6,
    "developer": 5, "dev ": 3,  # generic but useful in combination

    # Tier 4 — general tech/domain terms
    "api": 4, "python": 4, "node.js": 4, "express": 4, "postgresql": 4,
    "docker": 4, "next.js": 4, "langchain": 4, "automation": 4, "integrate": 4,
    "api integration": 4, "migration": 4, "prototype": 4, "backend": 4,
    "dashboard": 4, "saas": 4, "stripe": 4, "scraping": 4, "web scraper": 4,
    "agent": 4, "ai agent": 4, "chatbot": 4,

    # Tier 5 — implicit pain-point language, needs several to co-occur
    "stuck": 2, "give up": 2, "giving up": 2, "crashing": 2,
    "deploy": 2, "deployment": 2, "broken": 2, "doesn't work": 2, "not working": 2,
    "help me fix": 2, "desperate": 2, "launch": 2, "launching": 2, "deadline": 2,
    "spent weeks": 2, "spent days": 2, "tried everything": 2, "no idea what": 2,
    "bug": 2, "timing out": 2, "timeout": 2, "next week": 3,
    "keeps crashing": 6,  # persistent/production-level signal, worth more than
                           # a passing "crashing" mention

    # near-decision-point phrases — these signal someone at the edge of
    # paying for help, worth more than a generic pain-point mention
    "about to give up": 6, "trying to deploy": 4, "trying to fix": 4,
}
