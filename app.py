# app.py

import re
import sqlite3

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from rss_fetcher import init_db

DB_PATH = "nebula.db"

init_db(DB_PATH)

app = FastAPI(
    title="Nebula Search",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _contains_cjk(text: str) -> bool:
    """判斷字串是否包含中日韓文字（FTS5 對這類文字分詞效果差，改走 LIKE）"""
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))


def build_fts_query(text: str) -> str:
    """
    依照 SQLite 官方建議的做法：把每個 token 包在雙引號中，
    並將 token 內部的雙引號雙寫跳脫（"" -> 代表一個字面上的雙引號）。
    這樣可以避免 FTS5 把使用者輸入的任何符號誤判成查詢語法而噴 syntax error。
    """
    tokens = text.split()
    if not tokens:
        return '""'

    escaped_tokens = []
    for t in tokens:
        safe = t.replace('"', '""')
        if len(t) < 3:
            escaped_tokens.append(f'"{safe}"*')
        else:
            escaped_tokens.append(f'"{safe}"')

    return " ".join(escaped_tokens)


def search_like(conn, q: str, limit: int):
    """LIKE 查詢：用於中文查詢，或 FTS5 查詢失敗/無結果時的 fallback"""
    cur = conn.cursor()
    like_pat = f"%{q}%"
    cur.execute(
        """
        SELECT
            id, domain, title, link, summary,
            author, published, tags, 0.0 AS score
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
    return [dict(row) for row in cur.fetchall()]


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
):
    q = q.strip()
    if not q:
        return {"query": q, "count": 0, "results": []}

    conn = get_conn()
    results = []

    if _contains_cjk(q):
        results = search_like(conn, q, limit)
    else:
        try:
            fts_query = build_fts_query(q)
            cur = conn.cursor()
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
            results = [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            results = []

        if not results:
            results = search_like(conn, q, limit)

    conn.close()

    return {
        "query": q,
        "count": len(results),
        "results": results,
    }
