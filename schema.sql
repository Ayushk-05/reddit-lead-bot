CREATE TABLE IF NOT EXISTS posts (
    id              TEXT PRIMARY KEY,        -- reddit post id, dedup key
    subreddit       TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    url             TEXT NOT NULL,
    author          TEXT,
    created_utc     TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- top-level fields pulled out of `analysis` for fast filtering/sorting
    should_notify   BOOLEAN,
    lead_score      NUMERIC(3,1),            -- 0.0 - 10.0

    -- full JSON result from the single classify+draft call
    -- (intent, fit_score, confidence, urgency, budget, technologies,
    --  reasoning, summary, outreach_strategy, reply_messages — see ai_classifier.py)
    analysis        JSONB,

    notified        BOOLEAN NOT NULL DEFAULT false,
    notified_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_posts_created_utc ON posts (created_utc DESC);
CREATE INDEX IF NOT EXISTS idx_posts_lead_score ON posts (lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_posts_analysis_gin ON posts USING GIN (analysis);
