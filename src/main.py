import asyncio
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

from apify import Actor
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

TIKTOK_HOST = "https://www.tiktok.com"


def compact_to_int(value: Any) -> int:
    """Convert TikTok compact counts such as 12.3K, 4M, 1,234 to int."""
    if value is None:
        return 0
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return int(value)
    text = str(value).strip().replace("\xa0", "").replace(",", "").replace(" ", "")
    if not text or text.lower() in {"nan", "none", "null"}:
        return 0
    match = re.match(r"^([0-9]*\.?[0-9]+)([KkMmBb])?$", text)
    if not match:
        digits = re.sub(r"[^0-9]", "", text)
        return int(digits) if digits else 0
    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    return int(number * multiplier)


def classify_theme(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\b(mounjaro|tirzepatida|tirzepatide)\b", t):
        return "Mounjaro/Tirzepatida"
    if re.search(r"\b(ozempic|semaglutida|semaglutide)\b", t):
        return "Ozempic/Semaglutida"
    if re.search(r"\bwegovy\b", t):
        return "Wegovy"
    return "Outros"


def compute_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    likes = compact_to_int(item.get("diggCount") or item.get("likes"))
    comments = compact_to_int(item.get("commentCount") or item.get("comments"))
    shares = compact_to_int(item.get("shareCount") or item.get("shares"))
    saves = compact_to_int(item.get("collectCount") or item.get("saves"))
    views = compact_to_int(item.get("playCount") or item.get("views"))
    interactions = likes + comments + shares + saves
    engagement = (interactions / views * 100) if views > 0 else None
    score = (engagement * math.log10(views + 1)) if engagement is not None and views > 0 else 0
    item.update({
        "diggCount": likes,
        "commentCount": comments,
        "shareCount": shares,
        "collectCount": saves,
        "playCount": views,
        "interactions": interactions,
        "engagementRatePct": round(engagement, 4) if engagement is not None else None,
        "rankScore": round(score, 4),
    })
    return item


def normalize_video(raw: Dict[str, Any], source_url: str) -> Optional[Dict[str, Any]]:
    """Normalize a TikTok item collected from page state JSON or DOM fallback."""
    if not isinstance(raw, dict):
        return None

    video_id = raw.get("id") or raw.get("videoId") or raw.get("awemeId")
    author = raw.get("author") or raw.get("authorMeta") or {}
    stats = raw.get("stats") or raw.get("statsV2") or raw.get("statistics") or {}

    author_username = (
        author.get("uniqueId") or author.get("name") or raw.get("authorUniqueId") or raw.get("authorUsername")
    )
    author_nickname = author.get("nickname") or author.get("nickName") or raw.get("authorNickname")
    desc = raw.get("desc") or raw.get("description") or raw.get("text") or ""

    url = raw.get("webVideoUrl") or raw.get("url")
    if not url and author_username and video_id:
        url = f"{TIKTOK_HOST}/@{author_username}/video/{video_id}"

    if not url:
        return None

    item = {
        "id": str(video_id) if video_id else None,
        "url": url,
        "sourceUrl": source_url,
        "authorUsername": author_username,
        "authorNickname": author_nickname,
        "authorProfileUrl": f"{TIKTOK_HOST}/@{author_username}" if author_username else None,
        "description": desc,
        "createTime": raw.get("createTime") or raw.get("create_time"),
        "diggCount": stats.get("diggCount") or stats.get("digg_count") or raw.get("diggCount") or raw.get("likes"),
        "commentCount": stats.get("commentCount") or stats.get("comment_count") or raw.get("commentCount") or raw.get("comments"),
        "shareCount": stats.get("shareCount") or stats.get("share_count") or raw.get("shareCount") or raw.get("shares"),
        "collectCount": stats.get("collectCount") or stats.get("collect_count") or raw.get("collectCount") or raw.get("saves"),
        "playCount": stats.get("playCount") or stats.get("play_count") or raw.get("playCount") or raw.get("views"),
    }
    item["theme"] = classify_theme(f"{item.get('description', '')} {item.get('url', '')}")
    item["scrapedAt"] = datetime.now(timezone.utc).isoformat()
    return compute_metrics(item)


def walk_json(obj: Any) -> Iterable[Dict[str, Any]]:
    """Walk nested TikTok state JSON and yield objects that look like video items."""
    if isinstance(obj, dict):
        keys = set(obj.keys())
        looks_like_video = (
            ("stats" in keys or "statsV2" in keys or "statistics" in keys or "playCount" in keys)
            and ("id" in keys or "videoId" in keys or "awemeId" in keys or "desc" in keys)
        )
        if looks_like_video:
            yield obj
        for value in obj.values():
            yield from walk_json(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_json(value)


async def extract_state_json(page: Page) -> List[Dict[str, Any]]:
    scripts = await page.locator("script[type='application/json']").all()
    items: List[Dict[str, Any]] = []
    for script in scripts:
        try:
            txt = await script.text_content()
            if not txt:
                continue
            data = json.loads(txt)
            for obj in walk_json(data):
                items.append(obj)
        except Exception:
            continue
    return items


async def extract_dom_fallback(page: Page, source_url: str) -> List[Dict[str, Any]]:
    """Fallback for public pages: parse visible video links and nearby compact counters."""
    data = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href*="/video/"]')).map(a => {
            const card = a.closest('div') || a.parentElement;
            const text = card ? card.innerText : a.innerText;
            return { url: a.href, description: a.getAttribute('title') || a.innerText || '', rawText: text };
        })
        """
    )
    out = []
    for row in data:
        raw = row.get("rawText") or ""
        numbers = re.findall(r"([0-9]+(?:\.[0-9]+)?\s?[KkMmBb]?)", raw)
        # DOM labels change often. Keep only URL/description when metrics cannot be trusted.
        out.append(compute_metrics({
            "url": row.get("url"),
            "sourceUrl": source_url,
            "description": row.get("description") or raw[:300],
            "theme": classify_theme(f"{row.get('description', '')} {row.get('url', '')}"),
            "playCount": 0,
            "diggCount": 0,
            "commentCount": 0,
            "shareCount": 0,
            "collectCount": 0,
            "rawVisibleText": raw[:1000],
            "scrapedAt": datetime.now(timezone.utc).isoformat(),
        }))
    return out


async def collect_from_url(page: Page, url: str, max_videos: int, scroll_rounds: int) -> List[Dict[str, Any]]:
    await Actor.log.info(f"Opening {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        await Actor.log.warning(f"Timeout while opening {url}; trying to continue with partial content")

    await page.wait_for_timeout(4_000)
    last_height = 0
    for _ in range(scroll_rounds):
        await page.mouse.wheel(0, 2400)
        await page.wait_for_timeout(900)
        height = await page.evaluate("document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height

    raw_items = await extract_state_json(page)
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_items:
        item = normalize_video(raw, url)
        if item and item["url"] not in seen:
            seen.add(item["url"])
            normalized.append(item)
        if len(normalized) >= max_videos:
            break

    if not normalized:
        fallback = await extract_dom_fallback(page, url)
        for item in fallback:
            if item.get("url") and item["url"] not in seen:
                seen.add(item["url"])
                normalized.append(item)
            if len(normalized) >= max_videos:
                break

    return normalized


def build_urls(actor_input: Dict[str, Any]) -> List[str]:
    start_urls = actor_input.get("startUrls") or []
    urls = []
    for row in start_urls:
        if isinstance(row, str):
            urls.append(row)
        elif isinstance(row, dict) and row.get("url"):
            urls.append(row["url"])

    if not urls:
        for kw in actor_input.get("keywords") or []:
            urls.append(f"{TIKTOK_HOST}/search?q={quote_plus(str(kw))}")
    return urls


def keep_item(item: Dict[str, Any], actor_input: Dict[str, Any]) -> bool:
    min_views = int(actor_input.get("minViews", 5000))
    min_interactions = int(actor_input.get("minInteractions", 100))
    max_eng = float(actor_input.get("maxEngagementRatePct", 30))
    keep_outliers = bool(actor_input.get("keepOutliers", False))

    if item.get("playCount", 0) < min_views:
        item["filteredReason"] = "below_min_views"
        return False
    if item.get("interactions", 0) < min_interactions:
        item["filteredReason"] = "below_min_interactions"
        return False
    eng = item.get("engagementRatePct")
    item["possibleOutlier"] = bool(eng is not None and eng > max_eng)
    if item["possibleOutlier"] and not keep_outliers:
        item["filteredReason"] = "above_max_engagement_rate"
        return False
    return True


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        urls = build_urls(actor_input)
        max_videos = int(actor_input.get("maxVideosPerSource", 100))
        scroll_rounds = int(actor_input.get("scrollRounds", 12))
        headless = bool(actor_input.get("headless", True))

        if not urls:
            await Actor.log.warning("No URLs or keywords provided.")
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1365, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
            )
            page = await context.new_page()

            seen_urls = set()
            kept = 0
            for url in urls:
                items = await collect_from_url(page, url, max_videos, scroll_rounds)
                for item in items:
                    video_url = item.get("url")
                    if not video_url or video_url in seen_urls:
                        continue
                    seen_urls.add(video_url)
                    if keep_item(item, actor_input):
                        await Actor.push_data(item)
                        kept += 1

            await browser.close()
            await Actor.log.info(f"Finished. Kept {kept} videos after methodological filters.")


if __name__ == "__main__":
    asyncio.run(main())
