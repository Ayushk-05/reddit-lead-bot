-- Create table if it doesn't exist
CREATE TABLE IF NOT EXISTS posts (
    id              TEXT PRIMARY KEY,
    subreddit       TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    url             TEXT NOT NULL,
    author          TEXT,
    created_utc     TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    should_notify   BOOLEAN,
    lead_score      NUMERIC(3,1),
    analysis        JSONB,

    notified        BOOLEAN NOT NULL DEFAULT FALSE,
    notified_at     TIMESTAMPTZ
);

-- Add new columns safely if upgrading an existing database
ALTER TABLE posts
ADD COLUMN IF NOT EXISTS keyword_score INTEGER NOT NULL DEFAULT 0;

-- Create indexes safely
CREATE INDEX IF NOT EXISTS idx_posts_created_utc
ON posts (created_utc DESC);

CREATE INDEX IF NOT EXISTS idx_posts_lead_score
ON posts (lead_score DESC);

CREATE INDEX IF NOT EXISTS idx_posts_keyword_score
ON posts (keyword_score DESC);

CREATE INDEX IF NOT EXISTS idx_posts_analysis_gin
ON posts USING GIN (analysis);