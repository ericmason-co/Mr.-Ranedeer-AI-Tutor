import hashlib
from datetime import datetime
from apify_client import ApifyClient

from app.config import APIFY_API_TOKEN, LINKEDIN_PROFILE_URL, NICHE_KEYWORDS
from app.database import get_db, log_scrape

client = ApifyClient(APIFY_API_TOKEN)


def _make_id(*parts: str) -> str:
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _safe_int(val) -> int:
    try:
        return int(val or 0)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Profile posts — actor: atomus/linkedin-posts-scraper-pro
# Output fields: content, post_url, posted_at, author_name,
#                likes_count, comments_count, shares_count (+ more)
# ---------------------------------------------------------------------------

def scrape_profile_posts(limit: int = 30) -> list[dict]:
    run_input = {
        "profiles": [LINKEDIN_PROFILE_URL],
        "maxPostsPerProfile": limit,
        "includeReposts": False,
        "includeSharedPosts": True,
    }
    try:
        run = client.actor("atomus/linkedin-posts-scraper-pro").call(
            run_input=run_input, timeout_secs=180
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        # Filter out error/meta items returned by the actor
        items = [i for i in items if i.get("type") != "error"]
        log_scrape("profile_posts", "success", len(items))
        return items
    except Exception as e:
        log_scrape("profile_posts", "error", error=str(e))
        print(f"[scraper] profile posts error: {e}")
        return []


def save_profile_posts(raw_posts: list[dict]):
    if not raw_posts:
        return

    from app.ai import classify_pillar

    conn = get_db()
    for p in raw_posts:
        content = p.get("content") or p.get("text") or ""
        url = p.get("post_url") or p.get("postUrl") or p.get("url") or ""
        post_id = _make_id(url, content[:80])
        # atomus actor nests engagement under "engagement" key
        eng = p.get("engagement") or {}
        likes = _safe_int(eng.get("total_reactions") or p.get("likes_count") or p.get("likes"))
        comments = _safe_int(eng.get("comments") or p.get("comments_count") or p.get("comments"))
        shares = _safe_int(eng.get("shares") or p.get("shares_count") or p.get("shares"))
        posted_at = p.get("posted_at") or p.get("postedAt") or datetime.utcnow().isoformat()
        pillar = classify_pillar(content) if content else None

        conn.execute(
            """INSERT OR REPLACE INTO my_posts
               (id, url, content, likes, comments, shares, posted_at, pillar, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (post_id, url, content, likes, comments, shares, posted_at, pillar),
        )

        if pillar:
            conn.execute(
                """INSERT INTO pillar_tracking (pillar, last_posted_at, post_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(pillar) DO UPDATE SET
                     last_posted_at = MAX(excluded.last_posted_at, COALESCE(last_posted_at, '')),
                     post_count = post_count + 1""",
                (pillar, posted_at),
            )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Niche posts — actor: atomus/linkedin-posts-scraper-pro
# Scrapes posts from key STR/hospitality influencer profiles as niche signal.
# Add more LinkedIn profile URLs to NICHE_PROFILES in config to expand coverage.
# ---------------------------------------------------------------------------

NICHE_PROFILES = [
    "https://www.linkedin.com/in/wericmason/",  # seed with own profile for now
]


def scrape_niche_posts(days: int = 3, limit_per_keyword: int = 10) -> list[dict]:
    from app.config import NICHE_KEYWORDS
    all_posts: list[dict] = []

    run_input = {
        "profiles": NICHE_PROFILES,
        "maxPostsPerProfile": limit_per_keyword * 2,
        "includeReposts": False,
        "postedWithin": "1 week" if days <= 7 else "1 month",
    }
    try:
        run = client.actor("atomus/linkedin-posts-scraper-pro").call(
            run_input=run_input, timeout_secs=240
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        items = [i for i in items if i.get("type") != "error"]
        for item in items:
            item["_keyword"] = "niche"
        all_posts.extend(items)
    except Exception as e:
        log_scrape("niche_posts", "error", error=str(e))
        print(f"[scraper] niche posts error: {e}")

    all_posts.sort(
        key=lambda p: _safe_int(p.get("likes_count") or p.get("likes"))
        + _safe_int(p.get("comments_count") or p.get("comments")) * 3,
        reverse=True,
    )
    log_scrape("niche_posts", "success", len(all_posts))
    return all_posts


def save_niche_posts(raw_posts: list[dict]):
    if not raw_posts:
        return
    conn = get_db()
    for p in raw_posts:
        content = p.get("content") or p.get("text") or ""
        url = p.get("post_url") or p.get("url") or p.get("postUrl") or ""
        post_id = _make_id(url, content[:80])
        auth = p.get("author") if isinstance(p.get("author"), dict) else {}
        author = auth.get("name") or p.get("author_name") or p.get("authorName") or "Unknown"
        author_title = auth.get("headline") or p.get("author_headline") or p.get("authorHeadline") or ""
        eng = p.get("engagement") or {}
        likes = _safe_int(eng.get("total_reactions") or p.get("likes_count") or p.get("likes"))
        comments = _safe_int(eng.get("comments") or p.get("comments_count") or p.get("comments"))
        shares = _safe_int(eng.get("shares") or p.get("shares_count") or p.get("shares"))
        posted_at = p.get("posted_at") or p.get("postedAt") or datetime.utcnow().isoformat()
        keyword = p.get("_keyword") or ""

        conn.execute(
            """INSERT OR REPLACE INTO niche_posts
               (id, url, content, author, author_title, likes, comments, shares, posted_at, keyword, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (post_id, url, content, author, author_title, likes, comments, shares, posted_at, keyword),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Engagers — reuse search scraper with comment scraping
# ---------------------------------------------------------------------------

def scrape_post_engagers(post_urls: list[str]) -> list[dict]:
    all_engagers: list[dict] = []
    for url in post_urls[:5]:
        run_input = {
            "postUrls": [url],
            "scrapeComments": True,
            "maxComments": 50,
        }
        try:
            run = client.actor("curious_coder/linkedin-post-search-scraper").call(
                run_input=run_input, timeout_secs=180
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            for item in items:
                item["_source_post"] = url
            all_engagers.extend(items)
        except Exception as e:
            log_scrape("engagers", "error", error=str(e))
            print(f"[scraper] engager scrape error: {e}")

    log_scrape("engagers", "success", len(all_engagers))
    return all_engagers


def save_engagers(engagers: list[dict]):
    if not engagers:
        return
    conn = get_db()
    for e in engagers:
        name = e.get("authorName") or e.get("name") or "Unknown"
        title = e.get("authorHeadline") or e.get("title") or ""
        profile_url = e.get("authorProfileUrl") or e.get("profileUrl") or ""
        company = e.get("authorCompany") or e.get("company") or ""
        post_url = e.get("_source_post") or e.get("postUrl") or ""
        engager_id = _make_id(name, profile_url, post_url)

        conn.execute(
            """INSERT OR REPLACE INTO engagers
               (id, name, title, profile_url, company, post_url, engagement_type, found_at)
               VALUES (?, ?, ?, ?, ?, ?, 'comment', CURRENT_TIMESTAMP)""",
            (engager_id, name, title, profile_url, company, post_url),
        )

    conn.commit()
    conn.close()
