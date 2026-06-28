import json
import httpx
from app.config import ROBINREACH_API_KEY

_MCP_URL = "https://robinreach.com/mcp/v1/messages"
_linkedin_profile_id: int | None = None


def _mcp_call(action: str, **kwargs) -> dict:
    url = f"{_MCP_URL}?api_key={ROBINREACH_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "robinreach",
            "arguments": {"action": action, **kwargs},
        },
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            result = {}
            for line in resp.text.splitlines():
                if line.startswith("data: "):
                    try:
                        msg = json.loads(line[6:])
                        if "result" in msg:
                            result = msg["result"]
                    except Exception:
                        pass
            return result
        else:
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "RobinReach error"))
            return data.get("result", {})


def _text(result: dict) -> str:
    for item in result.get("content", []):
        if item.get("type") == "text":
            return item.get("text", "")
    return ""


def _get_linkedin_profile_id() -> int | None:
    global _linkedin_profile_id
    if _linkedin_profile_id:
        return _linkedin_profile_id
    result = _mcp_call("list_profiles")
    raw = _text(result)
    try:
        profiles = json.loads(raw)
        if isinstance(profiles, dict):
            profiles = profiles.get("profiles", [])
        for p in profiles:
            platform = (p.get("platform") or p.get("platform_type") or "").lower()
            if "linkedin" in platform:
                _linkedin_profile_id = int(p["id"])
                return _linkedin_profile_id
    except Exception as e:
        print(f"[robinreach] parse profiles error: {e} | raw: {raw[:300]}")
    return None


def create_linkedin_draft(content: str) -> dict:
    if not ROBINREACH_API_KEY:
        raise RuntimeError("ROBINREACH_API_KEY not configured")
    profile_id = _get_linkedin_profile_id()
    if not profile_id:
        raise RuntimeError("LinkedIn profile not found in RobinReach — ensure LinkedIn is connected")
    result = _mcp_call(
        "create_post",
        content=content,
        social_profile_ids=[profile_id],
        post_status="draft",
    )
    return result
