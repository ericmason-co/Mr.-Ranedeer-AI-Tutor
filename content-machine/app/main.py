import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from app import ai, scrapers
from app.config import DASHBOARD_PASSWORD
from app.database import get_db, init_db

security = HTTPBasic()
scheduler = BackgroundScheduler()
FRONTEND = Path(__file__).parent.parent / "frontend"


def verify(credentials: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        DASHBOARD_PASSWORD.encode("utf-8"),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def morning_scrape():
    print(f"[scheduler] morning scrape started at {datetime.utcnow().isoformat()}")
    posts = scrapers.scrape_profile_posts(limit=30)
    scrapers.save_profile_posts(posts)
    niche = scrapers.scrape_niche_posts(days=7)
    scrapers.save_niche_posts(niche)
    print(f"[scheduler] done — {len(posts)} profile posts, {len(niche)} niche posts")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(morning_scrape, "cron", hour=6, minute=30, id="morning")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan, title="LinkedIn Time Machine", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(verify)):
    return FileResponse(FRONTEND / "index.html")


# ── Briefing ────────────────────────────────────────────────────────────────

@app.get("/api/briefing")
async def get_briefing(_: str = Depends(verify)):
    conn = get_db()
    top_posts = conn.execute(
        "SELECT * FROM my_posts ORDER BY (likes + comments*3) DESC LIMIT 3"
    ).fetchall()
    pillars = conn.execute(
        "SELECT * FROM pillar_tracking ORDER BY last_posted_at ASC NULLS FIRST"
    ).fetchall()
    stats_row = conn.execute(
        "SELECT COUNT(*) as total, SUM(likes) as tl, SUM(comments) as tc, MIN(posted_at) as earliest, MAX(posted_at) as latest FROM my_posts"
    ).fetchone()
    last_scrape = conn.execute(
        "SELECT ran_at FROM scrape_log WHERE scrape_type='profile_posts' AND status='success' ORDER BY ran_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    now = datetime.utcnow()
    arc_data = []
    for p in pillars:
        days_ago = None
        if p["last_posted_at"]:
            try:
                last = datetime.fromisoformat(p["last_posted_at"].replace("Z", ""))
                days_ago = (now - last).days
            except Exception:
                pass
        arc_data.append({
            "pillar": p["pillar"],
            "last_posted_at": p["last_posted_at"],
            "days_ago": days_ago,
            "post_count": p["post_count"],
            "status": "overdue" if days_ago is None or days_ago > 14
                      else "due" if days_ago > 7
                      else "good",
        })

    return {
        "top_posts": [dict(p) for p in top_posts],
        "pillars": arc_data,
        "stats": {
            "total_posts": stats_row["total"] or 0,
            "total_likes": stats_row["tl"] or 0,
            "total_comments": stats_row["tc"] or 0,
            "earliest_post": stats_row["earliest"],
            "latest_post": stats_row["latest"],
        },
        "last_scrape": last_scrape["ran_at"] if last_scrape else None,
    }


@app.post("/api/briefing/refresh")
async def refresh_briefing(bg: BackgroundTasks, _: str = Depends(verify)):
    bg.add_task(morning_scrape)
    return {"status": "started"}


# ── Research ────────────────────────────────────────────────────────────────

@app.get("/api/research")
async def get_research(_: str = Depends(verify)):
    conn = get_db()
    posts = conn.execute(
        """SELECT * FROM niche_posts
           WHERE posted_at >= datetime('now', '-7 days')
           ORDER BY (likes + comments*3) DESC LIMIT 20"""
    ).fetchall()
    last_scrape = conn.execute(
        "SELECT ran_at FROM scrape_log WHERE scrape_type='niche_posts' AND status='success' ORDER BY ran_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "posts": [dict(p) for p in posts],
        "last_scrape": last_scrape["ran_at"] if last_scrape else None,
    }


@app.post("/api/research/refresh")
async def refresh_research(bg: BackgroundTasks, _: str = Depends(verify)):
    def _scrape():
        posts = scrapers.scrape_niche_posts(days=7)
        scrapers.save_niche_posts(posts)
    bg.add_task(_scrape)
    return {"status": "started"}


# ── Trends ──────────────────────────────────────────────────────────────────

@app.get("/api/trends")
async def get_trends(_: str = Depends(verify)):
    conn = get_db()
    posts = conn.execute(
        """SELECT * FROM niche_posts
           WHERE posted_at >= datetime('now', '-7 days')
           ORDER BY scraped_at DESC LIMIT 40"""
    ).fetchall()
    conn.close()
    trends = ai.cluster_trends([dict(p) for p in posts])
    return {"trends": trends}


# ── Lookalike ────────────────────────────────────────────────────────────────

@app.get("/api/lookalike")
async def get_lookalike(_: str = Depends(verify)):
    conn = get_db()
    # Prefer a post from the last 7 days; fall back to all-time top
    top = conn.execute(
        """SELECT * FROM my_posts
           WHERE posted_at >= datetime('now', '-7 days')
           ORDER BY (likes + comments*3) DESC LIMIT 1"""
    ).fetchone()
    if not top:
        top = conn.execute(
            "SELECT * FROM my_posts ORDER BY (likes + comments*3) DESC LIMIT 1"
        ).fetchone()
    conn.close()
    if not top:
        return {"angles": [], "source_post": None}
    post = dict(top)
    angles = ai.generate_lookalike_angles(
        post["content"] or "",
        {"likes": post["likes"], "comments": post["comments"]},
    )
    return {"angles": angles, "source_post": post}


# ── Narrative Arcs ───────────────────────────────────────────────────────────

@app.get("/api/arcs")
async def get_arcs(_: str = Depends(verify)):
    conn = get_db()
    pillars = conn.execute(
        "SELECT * FROM pillar_tracking ORDER BY last_posted_at ASC NULLS FIRST"
    ).fetchall()
    conn.close()

    now = datetime.utcnow()
    result = []
    for p in pillars:
        days_ago = None
        if p["last_posted_at"]:
            try:
                last = datetime.fromisoformat(p["last_posted_at"].replace("Z", ""))
                days_ago = (now - last).days
            except Exception:
                pass
        result.append({
            "pillar": p["pillar"],
            "last_posted_at": p["last_posted_at"],
            "days_ago": days_ago,
            "post_count": p["post_count"],
            "status": "overdue" if days_ago is None or days_ago > 14
                      else "due" if days_ago > 7
                      else "good",
        })
    return {"arcs": result}


# ── Recycler ─────────────────────────────────────────────────────────────────

@app.get("/api/recycler")
async def get_recycler(_: str = Depends(verify)):
    conn = get_db()
    posts = conn.execute(
        """SELECT * FROM my_posts
           WHERE posted_at >= datetime('now', '-7 days')
           ORDER BY (likes + comments*3) DESC LIMIT 10"""
    ).fetchall()
    conn.close()
    return {"posts": [dict(p) for p in posts]}


# ── Draft ────────────────────────────────────────────────────────────────────

@app.post("/api/draft")
async def generate_draft(request: Request, _: str = Depends(verify)):
    body = await request.json()
    angle = body.get("angle", {})
    source_post_id = body.get("source_post_id")
    conn = get_db()
    if source_post_id:
        row = conn.execute("SELECT * FROM my_posts WHERE id=?", (source_post_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM my_posts ORDER BY (likes+comments*3) DESC LIMIT 1"
        ).fetchone()
    conn.close()
    source_post = dict(row) if row else {}
    draft = ai.generate_post_draft(angle, source_post)
    return {"draft": draft}


# ── RobinReach ───────────────────────────────────────────────────────────────

@app.post("/api/send-to-robinreach")
async def send_to_robinreach(request: Request, _: str = Depends(verify)):
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="No content provided")
    try:
        from app import robinreach
        result = robinreach.create_linkedin_draft(content)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Comment Targets ───────────────────────────────────────────────────────────

@app.get("/api/comment-targets")
async def get_comment_targets(_: str = Depends(verify)):
    conn = get_db()
    posts = conn.execute(
        """SELECT * FROM niche_posts
           WHERE posted_at >= datetime('now', '-7 days')
           ORDER BY (likes + comments*3) DESC LIMIT 8"""
    ).fetchall()
    conn.close()
    posts_list = [dict(p) for p in posts]
    starters = ai.generate_comment_starters(posts_list)
    for i, p in enumerate(posts_list):
        p["comment_starter"] = starters[i] if i < len(starters) else ""
    return {"targets": posts_list}


# ── Engagement ───────────────────────────────────────────────────────────────

@app.get("/api/engagement")
async def get_engagement(_: str = Depends(verify)):
    """
    Surface ICP contacts from niche post authors.
    No additional scraper needed — uses data already collected by Research.
    """
    from app.config import ICP_TITLES
    conn = get_db()
    rows = conn.execute(
        """SELECT author, author_title, url, MAX(likes+comments*3) as score,
                  SUM(likes) as total_likes, COUNT(*) as post_count, MAX(posted_at) as last_post
           FROM niche_posts
           WHERE author IS NOT NULL AND author != '' AND author != 'Unknown'
           GROUP BY author
           ORDER BY score DESC
           LIMIT 50"""
    ).fetchall()
    conn.close()

    icp_terms = [t.lower() for t in ICP_TITLES]
    contacts = []
    for r in rows:
        title = (r["author_title"] or "").lower()
        is_icp = any(term in title for term in icp_terms)
        contacts.append({
            "name": r["author"],
            "title": r["author_title"] or "",
            "profile_url": r["url"] or "",
            "post_count": r["post_count"],
            "total_likes": r["total_likes"] or 0,
            "last_post": r["last_post"],
            "is_icp": is_icp,
        })

    icp = [c for c in contacts if c["is_icp"]]
    others = [c for c in contacts if not c["is_icp"]]
    return {"icp": icp, "others": others[:20]}
