import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
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
    niche = scrapers.scrape_niche_posts(days=1)
    scrapers.save_niche_posts(niche)
    print(f"[scheduler] done — {len(posts)} profile posts, {len(niche)} niche posts")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(morning_scrape, "cron", hour=6, minute=30, id="morning")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan, title="Content Machine 2000", docs_url=None, redoc_url=None)


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
        "SELECT COUNT(*) as total, SUM(likes) as tl, SUM(comments) as tc FROM my_posts"
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
        "SELECT * FROM niche_posts ORDER BY (likes + comments*3) DESC LIMIT 20"
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
        posts = scrapers.scrape_niche_posts(days=3)
        scrapers.save_niche_posts(posts)
    bg.add_task(_scrape)
    return {"status": "started"}


# ── Trends ──────────────────────────────────────────────────────────────────

@app.get("/api/trends")
async def get_trends(_: str = Depends(verify)):
    conn = get_db()
    posts = conn.execute(
        "SELECT * FROM niche_posts ORDER BY scraped_at DESC LIMIT 40"
    ).fetchall()
    conn.close()
    trends = ai.cluster_trends([dict(p) for p in posts])
    return {"trends": trends}


# ── Lookalike ────────────────────────────────────────────────────────────────

@app.get("/api/lookalike")
async def get_lookalike(_: str = Depends(verify)):
    conn = get_db()
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
           WHERE posted_at < datetime('now', '-30 days')
           ORDER BY (likes + comments*3) DESC LIMIT 10"""
    ).fetchall()
    conn.close()
    return {"posts": [dict(p) for p in posts]}


# ── Engagement ───────────────────────────────────────────────────────────────

@app.get("/api/engagement")
async def get_engagement(_: str = Depends(verify)):
    conn = get_db()
    engagers = conn.execute(
        "SELECT * FROM engagers ORDER BY found_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return {"engagers": [dict(e) for e in engagers]}


@app.post("/api/engagement/refresh")
async def refresh_engagement(bg: BackgroundTasks, _: str = Depends(verify)):
    def _scrape():
        conn = get_db()
        urls = conn.execute(
            "SELECT url FROM niche_posts WHERE url IS NOT NULL LIMIT 5"
        ).fetchall()
        conn.close()
        post_urls = [r["url"] for r in urls if r["url"]]
        if post_urls:
            raw = scrapers.scrape_post_engagers(post_urls)
            filtered = ai.filter_icp_engagers(raw)
            scrapers.save_engagers(filtered)
    bg.add_task(_scrape)
    return {"status": "started"}
