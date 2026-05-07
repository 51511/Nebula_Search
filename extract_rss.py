#!/usr/bin/env python3

import argparse
import asyncio
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import aiohttp

# optional uvloop
try:
    import uvloop

    asyncio.set_event_loop_policy(
        uvloop.EventLoopPolicy()
    )
except Exception:
    pass

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

CONCURRENCY = 100


INPUT_PATH = "/blogroll_graph.json" # 輸入Nebula結果路徑
OUTPUT_PATH = "rss_feeds.json"

TIMEOUT = aiohttp.ClientTimeout(
    total=15,
    connect=8,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

RSS_FALLBACK_PATHS = [

    # standard
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",

    # wordpress
    "/?feed=rss2",

    # blogger
    "/feeds/posts/default",
    "/feeds/posts/default?alt=rss",

    # atom
    "/atom",
    "/atom.xml",

    # misc
    "/rss2",
]

# relaxed feed regex
FEED_RE = re.compile(
    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\'][^"\']*(rss|atom|xml)[^"\']*["\']',
    re.I,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────


async def fetch_text(
    session,
    url,
):

    try:

        async with session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        ) as resp:

            if resp.status >= 400:
                return None

            raw = await resp.read()

            return raw.decode(
                "utf-8",
                errors="ignore",
            )

    except Exception:
        return None


# ─────────────────────────────────────────────
# RSS DISCOVERY
# ─────────────────────────────────────────────


def extract_feed_links(
    html,
    base_url,
):

    feeds = []

    # <link rel=alternate>
    matches = FEED_RE.findall(html)

    for m in matches:

        href = m[0]

        abs_url = urljoin(
            base_url,
            href
        )

        if (
            urlparse(abs_url).scheme
            in ("http", "https")
        ):
            feeds.append(abs_url)

    # fallback: search href keywords
    if not feeds:

        href_matches = re.findall(
            r'href=["\']([^"\']+)["\']',
            html,
            re.I,
        )

        for href in href_matches:

            h = href.lower()

            if any(
                kw in h
                for kw in (
                    "rss",
                    "feed",
                    "atom",
                    ".xml",
                )
            ):

                abs_url = urljoin(
                    base_url,
                    href
                )

                if (
                    urlparse(abs_url).scheme
                    in ("http", "https")
                ):
                    feeds.append(abs_url)

    # dedupe preserve order
    seen = set()

    result = []

    for f in feeds:

        if f not in seen:

            seen.add(f)

            result.append(f)

    return result


async def validate_feed(
    session,
    url,
):

    text = await fetch_text(
        session,
        url
    )

    if not text:
        return False

    t = text.lower()

    # relaxed detection
    if (
        "<rss" in t
        or "<feed" in t
        or "xmlns:atom" in t
        or "<entry>" in t
        or "<channel>" in t
    ):
        return True

    return False


async def probe_domain(
    session,
    domain,
    sem,
):

    root = f"https://{domain}"

    feeds = []

    # ─────────────────────────
    # homepage autodiscovery
    # ─────────────────────────

    async with sem:

        html = await fetch_text(
            session,
            root
        )

    if html:

        discovered = extract_feed_links(
            html,
            root,
        )

        if discovered:

            tasks = [
                validate_feed(
                    session,
                    url
                )
                for url in discovered
            ]

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            for url, ok in zip(
                discovered,
                results,
            ):

                if ok is True:
                    feeds.append(url)

    if feeds:
        return feeds

    # ─────────────────────────
    # fallback probing
    # ─────────────────────────

    candidate_urls = [
        root.rstrip("/") + path
        for path in RSS_FALLBACK_PATHS
    ]

    tasks = [
        validate_feed(
            session,
            url
        )
        for url in candidate_urls
    ]

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    for url, ok in zip(
        candidate_urls,
        results,
    ):

        if ok is True:

            feeds.append(url)

    # dedupe
    feeds = list(dict.fromkeys(feeds))

    return feeds


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────


async def extract_rss(graph):

    domains = list(graph.keys())

    log.info(
        f"共 {len(domains)} 個 domain，開始探索 RSS…"
    )

    sem = asyncio.Semaphore(
        CONCURRENCY
    )

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=4,
        ssl=False,
        ttl_dns_cache=300,
    )

    results = []

    completed = 0

    async with aiohttp.ClientSession(
        connector=connector
    ) as session:

        task_map = {

            asyncio.create_task(
                probe_domain(
                    session,
                    domain,
                    sem,
                )
            ): domain

            for domain in domains
        }

        for task in asyncio.as_completed(
            task_map
        ):

            domain = task_map[task]

            try:

                feeds = await task

            except Exception:

                feeds = []

            completed += 1

            percent = (
                completed
                / len(domains)
                * 100
            )

            if feeds:

                log.info(
                    f"[{completed}/{len(domains)} "
                    f"{percent:.1f}%] "
                    f"✓ {domain:40s} "
                    f"📡 {feeds[0]}"
                )

                for feed_url in feeds:

                    results.append({
                        "domain": domain,
                        "feed_url": feed_url,
                    })

            else:

                log.info(
                    f"[{completed}/{len(domains)} "
                    f"{percent:.1f}%] "
                    f"✗ {domain:40s}"
                )

    return results


# ─────────────────────────────────────────────
# ENTRY
# ─────────────────────────────────────────────

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        default=INPUT_PATH
    )

    parser.add_argument(
        "--output",
        default=OUTPUT_PATH
    )

    args = parser.parse_args()

    with open(
        args.input,
        encoding="utf-8",
    ) as f:

        graph = json.load(f)

    feeds = asyncio.run(
        extract_rss(graph)
    )

    with open(
        args.output,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            feeds,
            f,
            ensure_ascii=False,
            indent=2,
        )

    log.info("")
    log.info(
        f"✅ 完成！找到 "
        f"{len(feeds)} 個 RSS Feed"
    )

    log.info(
        f"已輸出至：{args.output}"
    )
