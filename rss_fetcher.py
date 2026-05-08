"""
Nebula RSS Fetcher & 搜尋引擎
==============================
把 blogroll_crawler.py 產生的 rss_feeds.json 當作「星圖」，
非同步抓取所有 RSS/Atom Feed，建立可搜尋的文章索引。

依賴：
    pip install aiohttp feedparser

用法：
    # 先跑爬蟲
    python blogroll_crawler.py

    # 再抓取所有 RSS
    python rss_fetcher.py

    # 指定來源與輸出
    python rss_fetcher.py --feeds rss_feeds.json --output articles.json

    # 搜尋
    python rss_fetcher.py --search "Python 教學"
    python rss_fetcher.py --search "生活" --limit 20
"""

import argparse
import asyncio
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
import feedparser

# ── 設定 ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "NebulaBot/1.0 (RSS aggregator; https://github.com/51511/Nebula_Search)",
    "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
CONCURRENCY = 8
REQUEST_DELAY = 0.2

DB_PATH = "nebula.db"
ARTICLES_JSON = "articles.json"


# ── SQLite 全文搜尋初始化 ─────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """
    建立 SQLite 資料庫，啟用 FTS5 全文搜尋。
    FTS5 支援中文分詞（trigram tokenizer），無需額外套件。
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 主資料表（儲存完整欄位）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            domain      TEXT NOT NULL,
            feed_url    TEXT NOT NULL,
            title       TEXT,
            link        TEXT UNIQUE,
            summary     TEXT,
            author      TEXT,
            published   TEXT,
            tags        TEXT,
            fetched_at  TEXT NOT NULL
        )
    """)

    # FTS5 虛擬表（用 trigram tokenizer，對中文效果最好）
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts
        USING fts5(
            title,
            summary,
            author,
            tags,
            content='articles',
            content_rowid='id',
            tokenize='trigram'
        )
    """)

    # 觸發器：自動同步主表 → FTS
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS articles_ai
        AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(rowid, title, summary, author, tags)
            VALUES (new.id, new.title, new.summary, new.author, new.tags);
        END
    """)

    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS articles_ad
        AFTER DELETE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, title, summary, author, tags)
            VALUES ('delete', old.id, old.title, old.summary, old.author, old.tags);
        END
    """)

    conn.commit()
    return conn


# ── RSS 解析工具 ──────────────────────────────────────────────────────────────

def clean_html(text: str) -> str:
    """移除 HTML 標籤，保留純文字"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_date(entry) -> str:
    """嘗試從 feedparser entry 取得發布時間，回傳 ISO 8601 字串"""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = datetime(*val[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return ""


def parse_feed(raw_bytes: bytes, feed_url: str, domain: str) -> list[dict]:
    """
    用 feedparser 解析 RSS/Atom，回傳文章清單。
    feedparser 接受 bytes，自動處理編碼。
    """
    parsed = feedparser.parse(raw_bytes)

    if parsed.bozo and not parsed.entries:
        log.warning(f"  ⚠ feedparser 解析失敗: {feed_url}")
        return []

    articles = []
    for entry in parsed.entries:
        title   = clean_html(getattr(entry, "title", "") or "")
        link    = getattr(entry, "link", "") or ""
        summary = clean_html(getattr(entry, "summary", "") or
                             getattr(entry, "content", [{}])[0].get("value", ""))
        author  = getattr(entry, "author", "") or ""
        tags    = ", ".join(
            t.get("term", "") for t in getattr(entry, "tags", []) if t.get("term")
        )
        published = parse_date(entry)

        if not title and not link:
            continue

        articles.append({
            "domain":     domain,
            "feed_url":   feed_url,
            "title":      title[:500],      # 防止超長標題
            "link":       link[:1000],
            "summary":    summary[:3000],   # 保留摘要，節省空間
            "author":     author[:200],
            "published":  published,
            "tags":       tags[:500],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    return articles


# ── 非同步抓取 ────────────────────────────────────────────────────────────────

async def fetch_feed(
    session: aiohttp.ClientSession,
    feed_info: dict,
    sem: asyncio.Semaphore,
) -> list[dict]:
    """抓取單一 RSS Feed，回傳文章清單"""
    domain   = feed_info["domain"]
    feed_url = feed_info["feed_url"]

    async with sem:
        await asyncio.sleep(REQUEST_DELAY)
        try:
            async with session.get(
                feed_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    log.warning(f"  ✗ {domain} → HTTP {resp.status}")
                    return []

                raw = await resp.read()
                articles = parse_feed(raw, feed_url, domain)
                log.info(f"  ✓ {domain:40s} → {len(articles)} 篇文章")
                return articles

        except asyncio.TimeoutError:
            log.warning(f"  ✗ {domain} → 超時")
        except Exception as e:
            log.warning(f"  ✗ {domain} → {type(e).__name__}: {e}")

    return []


async def fetch_all_feeds(feeds: list[dict]) -> list[dict]:
    """非同步抓取所有 RSS Feed"""
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=2,
        ssl=False,
        ttl_dns_cache=300,
    )

    all_articles = []
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_feed(session, feed, sem) for feed in feeds]
        results = await asyncio.gather(*tasks)
        for articles in results:
            all_articles.extend(articles)

    return all_articles


# ── 儲存 ──────────────────────────────────────────────────────────────────────

def save_to_db(articles: list[dict], conn: sqlite3.Connection) -> int:
    """
    批次寫入文章到 SQLite，重複的 link 自動跳過（INSERT OR IGNORE）。
    回傳新增數量。
    """
    cur = conn.cursor()
    inserted = 0

    for art in articles:
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO articles
                    (domain, feed_url, title, link, summary, author, published, tags, fetched_at)
                VALUES
                    (:domain, :feed_url, :title, :link, :summary, :author, :published, :tags, :fetched_at)
                """,
                art,
            )
            if cur.rowcount > 0:
                inserted += 1
        except sqlite3.Error as e:
            log.error(f"DB 寫入失敗: {e} — {art.get('link', '')}")

    conn.commit()
    return inserted


def save_to_json(articles: list[dict], output_path: str = ARTICLES_JSON):
    """同時輸出 JSON，方便其他工具使用"""
    # 如果已有舊資料，合併並去重
    existing = []
    if Path(output_path).exists():
        with open(output_path, encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    existing_links = {a["link"] for a in existing if a.get("link")}
    new_articles = [a for a in articles if a.get("link") not in existing_links]
    combined = existing + new_articles

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    log.info(f"JSON 輸出至 {output_path}（新增 {len(new_articles)} 篇，共 {len(combined)} 篇）")
    return len(new_articles)


# ── 搜尋引擎 ──────────────────────────────────────────────────────────────────

def search(query: str, conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """
    使用 SQLite FTS5 全文搜尋。
    Trigram tokenizer 對中文效果良好，不需要額外分詞。

    短詞處理（< 3 字元）：
    - FTS5 trigram 最短需要 3 字元，短詞搜尋必然空白。
    - 先嘗試 FTS wildcard（在每個 token 末尾加 *），讓 trigram index 做前綴比對。
    - 若 FTS 仍無結果，fallback 到全表 LIKE 搜尋（較慢但保底）。
    """
    cur = conn.cursor()
    results = []

    # ── FTS 搜尋（優先）────────────────────────────────────────────────────
    # 短詞（< 3 字元）：把每個 token 都加上 * 做前綴匹配
    # 長詞：直接用原始 query（BM25 表現最好）
    def _build_fts_query(q: str) -> str:
        tokens = q.split()
        if any(len(t) < 3 for t in tokens):
            # 每個 token 補 wildcard，讓 trigram index 展開前綴
            return " ".join(t + "*" for t in tokens)
        return q

    fts_query = _build_fts_query(query)

    try:
        cur.execute(
            """
            SELECT
                a.id,
                a.domain,
                a.title,
                a.link,
                a.summary,
                a.author,
                a.published,
                a.tags,
                bm25(articles_fts) AS score
            FROM articles_fts
            JOIN articles a ON a.id = articles_fts.rowid
            WHERE articles_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, limit),
        )
        columns = ["id", "domain", "title", "link", "summary", "author", "published", "tags", "score"]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError as e:
        # query 語法錯誤時（如含特殊字元）直接跳 fallback
        log.debug(f"FTS 查詢失敗，改用 LIKE: {e}")

    # ── LIKE fallback（短詞或 FTS 零結果時）────────────────────────────────
    if not results:
        like_pat = f"%{query}%"
        cur.execute(
            """
            SELECT
                id,
                domain,
                title,
                link,
                summary,
                author,
                published,
                tags,
                0.0 AS score
            FROM articles
            WHERE title   LIKE ?
               OR summary LIKE ?
               OR author  LIKE ?
               OR tags    LIKE ?
            ORDER BY published DESC
            LIMIT ?
            """,
            (like_pat, like_pat, like_pat, like_pat, limit),
        )
        columns = ["id", "domain", "title", "link", "summary", "author", "published", "tags", "score"]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
        if results:
            log.debug(f"FTS 無結果，LIKE fallback 找到 {len(results)} 筆")

    return results


def print_search_results(results: list[dict], query: str):
    """格式化輸出搜尋結果"""
    if not results:
        print(f"\n❌ 沒有找到關於「{query}」的結果")
        return

    print(f"\n🔍 搜尋「{query}」— 找到 {len(results)} 筆結果\n")
    print("─" * 70)

    for i, r in enumerate(results, 1):
        title     = r["title"] or "(無標題)"
        domain    = r["domain"]
        published = r["published"][:10] if r["published"] else "日期不明"
        summary   = (r["summary"] or "")[:150].replace("\n", " ")
        link      = r["link"] or ""

        print(f"[{i}] {title}")
        print(f"     🌐 {domain}  |  📅 {published}")
        if summary:
            print(f"     {summary}…")
        print(f"     🔗 {link}")
        print()


# ── 統計工具 ──────────────────────────────────────────────────────────────────

def print_stats(conn: sqlite3.Connection):
    """顯示資料庫統計資訊"""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM articles")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT domain) FROM articles")
    domains = cur.fetchone()[0]

    cur.execute("""
        SELECT domain, COUNT(*) as cnt
        FROM articles
        GROUP BY domain
        ORDER BY cnt DESC
        LIMIT 10
    """)
    top_domains = cur.fetchall()

    cur.execute("""
        SELECT DATE(published) as day, COUNT(*) as cnt
        FROM articles
        WHERE published != ''
        GROUP BY day
        ORDER BY day DESC
        LIMIT 7
    """)
    recent_days = cur.fetchall()

    print("\n" + "=" * 60)
    print("Nebula 資料庫統計")
    print("=" * 60)
    print(f"\n  總文章數：{total}")
    print(f"  來源站點：{domains} 個")

    print(f"\n  文章最多的 10 個站：")
    for domain, cnt in top_domains:
        print(f"    {domain:40s}  {cnt} 篇")

    if recent_days:
        print(f"\n  近期發文（依日期）：")
        for day, cnt in recent_days:
            print(f"    {day}  →  {cnt} 篇")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nebula RSS 抓取與搜尋引擎")
    parser.add_argument("--feeds",   default="rss_feeds.json",  help="RSS 清單 JSON（由 blogroll_crawler.py 產生）")
    parser.add_argument("--db",      default=DB_PATH,           help="SQLite 資料庫路徑")
    parser.add_argument("--output",  default=ARTICLES_JSON,     help="文章 JSON 輸出路徑")
    parser.add_argument("--search",  default="",                help="搜尋關鍵字（跳過抓取，直接搜）")
    parser.add_argument("--limit",   type=int, default=10,      help="搜尋結果數量上限")
    parser.add_argument("--stats",   action="store_true",       help="顯示資料庫統計")
    args = parser.parse_args()

    conn = init_db(args.db)

    # ── 搜尋模式 ──
    if args.search:
        results = search(args.search, conn, limit=args.limit)
        print_search_results(results, args.search)
        conn.close()
        exit(0)

    # ── 統計模式 ──
    if args.stats:
        print_stats(conn)
        conn.close()
        exit(0)

    # ── 抓取模式 ──
    feeds_path = Path(args.feeds)
    if not feeds_path.exists():
        log.error(f"找不到 RSS 清單：{args.feeds}")
        log.error("請先執行 python blogroll_crawler.py 來產生此檔案")
        exit(1)

    with open(feeds_path, encoding="utf-8") as f:
        feeds = json.load(f)

    log.info(f"載入 {len(feeds)} 個 RSS Feed，開始抓取…")
    articles = asyncio.run(fetch_all_feeds(feeds))
    log.info(f"\n共抓取 {len(articles)} 篇文章")

    # 寫入 DB
    new_count = save_to_db(articles, conn)
    log.info(f"新增 {new_count} 篇文章到資料庫")

    # 輸出 JSON
    save_to_json(articles, args.output)

    # 顯示統計
    print_stats(conn)

    conn.close()
    log.info("\n✅ 完成！執行以下指令來搜尋：")
    log.info("   python rss_fetcher.py --search '你的關鍵字'")
