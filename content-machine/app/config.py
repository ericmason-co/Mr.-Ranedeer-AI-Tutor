import os
from dotenv import load_dotenv

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LINKEDIN_PROFILE_URL = os.getenv("LINKEDIN_PROFILE_URL", "https://www.linkedin.com/in/wericmason/")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "content2000")

CONTENT_PILLARS = [
    "Short-Term Rentals",
    "Vacation Rentals",
    "Short-Term Rental Technology",
    "AI",
    "Hospitality",
]

NICHE_KEYWORDS = [
    "short-term rentals",
    "vacation rentals",
    "Airbnb host",
    "STR technology",
    "hospitality AI",
]

ICP_TITLES = [
    "short-term rental",
    "vacation rental",
    "airbnb",
    "str manager",
    "property manager",
    "vrbo",
    "hospitality tech",
    "str owner",
]
