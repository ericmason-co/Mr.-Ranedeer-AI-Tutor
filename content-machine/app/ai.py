import json
import anthropic
from app.config import ANTHROPIC_API_KEY, CONTENT_PILLARS, ICP_TITLES

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_CONTEXT = (
    "You are a LinkedIn content strategist specializing in short-term rentals, "
    "vacation rentals, STR technology, AI, and hospitality. "
    "Your audience is STR managers, Airbnb hosts, vacation rental operators, and hospitality tech founders."
)


PILLAR_DESCRIPTIONS = {
    "Short-Term Rentals": "General STR industry news, regulations, market trends, property management operations, Airbnb/VRBO platform news, host strategy, pricing, reviews, OTA dynamics.",
    "Vacation Rentals": "Vacation rental specific topics: guest experience, property design/amenities, destination travel, family/leisure stays, beach/mountain/cabin rentals, vacation home ownership.",
    "Short-Term Rental Technology": "Software, platforms, and tech tools built FOR STR operators: PMS systems, channel managers, dynamic pricing tools, automation, smart home tech, STR-specific SaaS.",
    "AI": "Artificial intelligence, machine learning, LLMs, ChatGPT, Claude, AI tools and their applications across any industry, AI strategy, AI impact on jobs/business.",
    "Hospitality": "Hotels, resorts, broader hospitality industry, restaurant/F&B, travel/tourism trends, customer service culture, hospitality leadership, guest satisfaction beyond STR.",
}


def classify_pillar(post_content: str) -> str:
    pillar_list = "\n".join(
        f"- {p}: {PILLAR_DESCRIPTIONS[p]}" for p in CONTENT_PILLARS
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            system=SYSTEM_CONTEXT,
            messages=[{
                "role": "user",
                "content": (
                    "Classify this LinkedIn post into exactly ONE of the pillars below. "
                    "Pick the MOST SPECIFIC match — if a post is about AI tools, pick AI not Short-Term Rentals. "
                    "If about hotel operations, pick Hospitality not Short-Term Rentals. "
                    "Only use Short-Term Rentals if the post is primarily about STR business/operations/market and doesn't fit a more specific pillar. "
                    "Reply with ONLY the pillar name, nothing else.\n\n"
                    f"Pillars:\n{pillar_list}\n\n"
                    f"Post:\n{post_content[:500]}"
                ),
            }],
        )
        result = resp.content[0].text.strip()
        for pillar in CONTENT_PILLARS:
            if pillar.lower() in result.lower():
                return pillar
    except Exception as e:
        print(f"[ai] classify_pillar error: {e}")
    return CONTENT_PILLARS[0]


def generate_lookalike_angles(post_content: str, stats: dict) -> list[dict]:
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            system=SYSTEM_CONTEXT,
            messages=[{
                "role": "user",
                "content": (
                    f"This LinkedIn post performed well "
                    f"({stats.get('likes', 0)} likes, {stats.get('comments', 0)} comments):\n\n"
                    f"---\n{post_content[:700]}\n---\n\n"
                    "Generate 5 adjacent content angles exploring different facets of this topic. "
                    "Return a JSON array only, no other text:\n"
                    '[{"angle":"title","description":"one sentence","hook":"opening line for the post"}]'
                ),
            }],
        )
        text = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"[ai] lookalike error: {e}")
        return []


def cluster_trends(posts: list[dict]) -> list[dict]:
    if not posts:
        return []
    summaries = []
    for p in posts[:25]:
        content = (p.get("content") or p.get("text") or "")[:180]
        likes = p.get("likes", 0) or 0
        summaries.append(f"[{likes} likes] {content}")

    posts_text = "\n\n".join(summaries)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            system=SYSTEM_CONTEXT,
            messages=[{
                "role": "user",
                "content": (
                    "Analyze these LinkedIn posts and identify the top 5 trending topics.\n\n"
                    f"Posts:\n{posts_text}\n\n"
                    "Return JSON only, no other text:\n"
                    '[{"topic":"name","momentum":"high|medium|low","summary":"why trending","post_count":0}]'
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"[ai] cluster_trends error: {e}")
        return []


def generate_post_draft(angle: dict, source_post: dict) -> str:
    hook = angle.get("hook", "")
    description = angle.get("description", "")
    title = angle.get("angle", "")
    source_content = (source_post.get("content") or "")[:600]
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=SYSTEM_CONTEXT,
            messages=[{
                "role": "user",
                "content": (
                    f"Write a LinkedIn post for an STR/vacation rental industry expert.\n\n"
                    f"Topic: {title}\n"
                    f"Angle: {description}\n"
                    f"Opening hook (use this or riff on it): {hook}\n\n"
                    f"Style reference — write in the same voice as this high-performing post:\n---\n{source_content}\n---\n\n"
                    "Rules:\n"
                    "- 150-250 words\n"
                    "- Short punchy paragraphs with line breaks between them\n"
                    "- First person, direct, opinionated — take a clear stance\n"
                    "- End with a question or CTA\n"
                    "- No hashtags\n"
                    "Return ONLY the post text, nothing else."
                ),
            }],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"[ai] draft error: {e}")
        return ""


def generate_comment_starters(posts: list[dict]) -> list[str]:
    if not posts:
        return []
    post_list = ""
    for i, p in enumerate(posts[:8]):
        content = (p.get("content") or p.get("text") or "")[:200]
        author = p.get("author") or "Unknown"
        post_list += f"{i+1}. [{author}]: {content}\n\n"
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
            system=SYSTEM_CONTEXT,
            messages=[{
                "role": "user",
                "content": (
                    "For each LinkedIn post below, write a thoughtful 1-2 sentence comment that "
                    "an STR industry expert would leave to add genuine value and boost their visibility. "
                    "Be specific to the post content — not generic. Sound like a peer, not a fan.\n\n"
                    f"Posts:\n{post_list}\n"
                    "Return a JSON array of strings, one comment per post:\n"
                    '["comment 1", "comment 2", ...]'
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"[ai] comment_starters error: {e}")
        return []


def filter_icp_engagers(engagers: list[dict]) -> list[dict]:
    icp_terms = [t.lower() for t in ICP_TITLES]
    result = []
    for e in engagers:
        title = (e.get("authorHeadline") or e.get("title") or "").lower()
        company = (e.get("authorCompany") or e.get("company") or "").lower()
        if any(term in title or term in company for term in icp_terms):
            result.append(e)
    return result
