import json
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager
from config import DATABASE_URL


@contextmanager
def get_conn():
    conn = psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def post_exists(post_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM posts WHERE id = %s", (post_id,))
            return cur.fetchone() is not None


def insert_raw_post(post: dict):
    """Insert a post before analysis (so we never re-fetch/re-process it).
    post['keyword_score'] must be set — see reddit_fetcher.keyword_score."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO posts (id, subreddit, title, body, url, author, created_utc, keyword_score)
                VALUES (%(id)s, %(subreddit)s, %(title)s, %(body)s, %(url)s, %(author)s, %(created_utc)s, %(keyword_score)s)
                ON CONFLICT (id) DO NOTHING
                """,
                post,
            )


def save_analysis(post_id: str, analysis: dict):
    """Store the full JSON result from ai_classifier.analyze_post, plus the
    two fields we filter/sort on at the SQL level."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE posts SET
                    should_notify = %(should_notify)s,
                    lead_score = %(lead_score)s,
                    analysis = %(analysis)s
                WHERE id = %(id)s
                """,
                {
                    "id": post_id,
                    "should_notify": analysis["should_notify"],
                    "lead_score": analysis["lead_score"],
                    "analysis": json.dumps(analysis),
                },
            )


def mark_notified(post_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE posts SET notified = true, notified_at = now() WHERE id = %s",
                (post_id,),
            )


def get_unanalyzed_posts(limit: int = None):
    """Posts with no analysis yet, strongest keyword-score candidates first.
    If `limit` is given (see config.MAX_GEMINI_CALLS), only that many rows
    are returned — the rest stay unanalyzed and get picked up (and
    re-ranked) on the next run rather than being skipped forever."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            query = (
                "SELECT * FROM posts WHERE analysis IS NULL "
                "ORDER BY keyword_score DESC, created_utc ASC"
            )
            params = ()
            if limit is not None:
                query += " LIMIT %s"
                params = (limit,)
            cur.execute(query, params)
            return cur.fetchall()


def get_leads_to_notify(min_score: float):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM posts
                WHERE should_notify = true
                  AND notified = false
                  AND lead_score >= %s
                ORDER BY lead_score DESC
                """,
                (min_score,),
            )
            return cur.fetchall()
