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
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
# Free tier is ~10 requests/minute — space out calls in main.py's classify loop
# so a busy run doesn't slam into a 429. 6.5s/call keeps you under that ceiling.
GEMINI_RATE_LIMIT_DELAY = float(os.environ.get("GEMINI_RATE_LIMIT_DELAY", 6.5))

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DATABASE_URL = os.environ["DATABASE_URL"]

MIN_SCORE_TO_NOTIFY = float(os.environ.get("MIN_SCORE_TO_NOTIFY", 6.5))
POST_LOOKBACK_LIMIT = int(os.environ.get("POST_LOOKBACK_LIMIT", 25))

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

# Cheap pre-filter before we spend an LLM call on a post.
# Keep this loose on purpose — the AI filter does the real thinking.
# It's mostly here to cut obvious junk (memes, "how do I center a div" etc.)
KEYWORDS = [
    # explicit hiring signals
    "hire", "hiring", "looking for a dev", "looking for a developer",
    "need a developer", "need a dev", "freelancer", "contractor",
    "budget", "paid", "pay you", "willing to pay", "compensation",
    "build my", "build a", "mvp", "backend", "api", "developer needed",

    # implicit pain-point signals (the interesting stuff)
    "stuck", "give up", "giving up", "crashing", "keeps crashing",
    "deploy", "deployment", "broken", "doesn't work", "not working",
    "help me fix", "desperate", "launch", "launching", "deadline",
    "spent weeks", "spent days", "tried everything", "no idea what",
]
