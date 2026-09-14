import httpx
from bs4 import BeautifulSoup

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


def fetch_related_links(query: str, limit: int = 6) -> list[dict]:
    """Scrape DuckDuckGo's no-JS HTML results page for related links/topics.

    No API key required. Returns a list of {title, url, snippet} dicts.
    """
    if not query or not query.strip():
        return []

    resp = httpx.post(
        DUCKDUCKGO_HTML_URL,
        data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (compatible; PoliceIntelAssistant/1.0)"},
        timeout=10,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result"):
        title_el = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        if not title_el or not title_el.get("href"):
            continue
        results.append({
            "title": title_el.get_text(strip=True),
            "url": title_el["href"],
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
        if len(results) >= limit:
            break

    return results
