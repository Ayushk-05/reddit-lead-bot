"""
Single-call lead engine: qualifies a Reddit post AND drafts outreach in one
Gemini call. Uses Gemini's native JSON mode (response_mime_type) so the model
is constrained to valid JSON at the API level, not just prompted to produce it.

Why one call instead of two (classify, then draft):
- Cheaper — one round trip instead of two.
- The model reasons about fit/strategy once and writes messages from that
  same reasoning, instead of re-deriving context from scratch in a second call.
- Simpler pipeline: one function, one JSON shape, one place that can fail.

Why Gemini: free tier (Gemini 2.5 Flash), no billing required to start.
Trade-off: free tier is rate-limited to ~10 requests/minute — main.py spaces
out calls with GEMINI_RATE_LIMIT_DELAY to stay under that.
"""
import json
import logging
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, DEVELOPER_PROFILE

logger = logging.getLogger("ai_classifier")

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """You are an elite freelance lead qualification assistant.

Your job is to analyze Reddit posts and determine whether they represent a genuine
freelance opportunity for this developer, then draft outreach if it's worth pursuing.

Developer's real background (do not claim anything outside this in outreach):
{profile}

Your goals:
1. Detect explicit hiring intent.
2. Detect implicit buying intent.
3. Ignore obvious non-leads.
4. Estimate how well this opportunity matches the developer's actual skills above.
5. Generate natural outreach messages that DO NOT sound AI-generated or salesy.

A lead is EXPLICIT if they directly ask for: a developer, freelancer, contractor,
technical cofounder, agency, backend help, API help.

A lead is IMPLICIT if the author is clearly struggling with an important technical
problem and may realistically pay someone, for example: launch is next week, backend
keeps crashing, deployment issues, production outage, deadlines, client work, repeated
frustration, "I've spent weeks on this."

These are NOT leads: homework, tutorials, memes, career advice, learning questions,
coding exercises, general discussions, people advertising their own services.

Rules for outreach (only generate if should_notify is true):
- Never exaggerate experience, invent projects, or claim something not in the profile above.
- Never sound desperate or like marketing.
- Reference something specific from the actual Reddit post — never generic.
- Keep each message under 120 words.
- End with a low-pressure invitation (not "let's hop on a call").
- Write like a real engineer talking to another person, matching the subreddit's tone.

Before writing the messages, work out an outreach_strategy first (opening hook, the
one technical observation to make, the call to action) and write all three message
variants FROM that strategy. This produces more natural, less repetitive messages
than jumping straight to the text.

If should_notify is false, set outreach_strategy to null and reply_messages to an
empty array — don't waste effort drafting outreach for posts that aren't worth
pursuing.

Respond with JSON matching this exact shape:

{{
  "should_notify": boolean,
  "lead_score": number,
  "fit_score": number,
  "confidence": number,
  "intent": {{"explicit": boolean, "implicit": boolean}},
  "urgency": number,
  "budget": "high" | "medium" | "low" | "unknown",
  "likely_to_pay": boolean,
  "technologies": ["string", ...],
  "category": "string",
  "reasoning": ["string", ...],
  "summary": "string",
  "outreach_strategy": {{"opening_hook": "string", "technical_observation": "string", "cta": "string"}} | null,
  "reply_messages": [
    {{"style": "friendly", "message": "string"}},
    {{"style": "technical", "message": "string"}},
    {{"style": "founder", "message": "string"}}
  ]
}}
"""

USER_TEMPLATE = """Analyze this Reddit opportunity.

Title: {title}
Subreddit: r/{subreddit}
Author: {author}
Body: {body}"""


def analyze_post(post: dict) -> dict:
    """
    Single call: qualifies the lead AND drafts outreach if it qualifies.
    Returns the full parsed JSON dict on success, or a safe "not a lead"
    fallback dict on any failure (API error, bad JSON, etc).
    """
    system = SYSTEM_PROMPT.format(profile=DEVELOPER_PROFILE.strip())
    user_msg = USER_TEMPLATE.format(
        title=post["title"],
        subreddit=post["subreddit"],
        author=post.get("author", "unknown"),
        body=(post.get("body") or "")[:3000],
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                max_output_tokens=1500,
            ),
        )
        result = json.loads(response.text)

        # normalize/guard the fields we rely on elsewhere so a slightly
        # malformed model response can't crash the pipeline downstream
        result["should_notify"] = bool(result.get("should_notify", False))
        result["lead_score"] = float(result.get("lead_score", 0.0))
        result.setdefault("reply_messages", [])
        result.setdefault("outreach_strategy", None)

        return result

    except Exception as e:
        logger.error(f"Analysis failed for post {post.get('id')}: {e}")
        return {
            "should_notify": False,
            "lead_score": 0.0,
            "fit_score": 0.0,
            "confidence": 0.0,
            "intent": {"explicit": False, "implicit": False},
            "urgency": 0,
            "budget": "unknown",
            "likely_to_pay": False,
            "technologies": [],
            "category": "unknown",
            "reasoning": ["analysis_failed"],
            "summary": "Analysis failed — see logs.",
            "outreach_strategy": None,
            "reply_messages": [],
        }
