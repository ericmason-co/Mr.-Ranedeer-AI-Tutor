import sqlite3
from pathlib import Path
from app.config import CONTENT_PILLARS

DB_PATH = Path(__file__).parent.parent / "data" / "content_machine.db"


def get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS my_posts (
            id TEXT PRIMARY KEY,
            url TEXT,
            content TEXT,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            posted_at TEXT,
            pillar TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS niche_posts (
            id TEXT PRIMARY KEY,
            url TEXT,
            content TEXT,
            author TEXT,
            author_title TEXT,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            posted_at TEXT,
            keyword TEXT,
            scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pillar_tracking (
            pillar TEXT PRIMARY KEY,
            last_posted_at TEXT,
            post_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS engagers (
            id TEXT PRIMARY KEY,
            name TEXT,
            title TEXT,
            profile_url TEXT,
            company TEXT,
            post_url TEXT,
            engagement_type TEXT DEFAULT 'comment',
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_type TEXT,
            status TEXT,
            items_found INTEGER DEFAULT 0,
            error TEXT,
            ran_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    for pillar in CONTENT_PILLARS:
        conn.execute(
            "INSERT OR IGNORE INTO pillar_tracking (pillar, last_posted_at, post_count) VALUES (?, NULL, 0)",
            (pillar,),
        )
    conn.commit()
    conn.close()


def log_scrape(scrape_type: str, status: str, items_found: int = 0, error: str = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO scrape_log (scrape_type, status, items_found, error) VALUES (?, ?, ?, ?)",
        (scrape_type, status, items_found, error),
    )
    conn.commit()
    conn.close()
