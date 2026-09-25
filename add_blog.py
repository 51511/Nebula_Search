#!/usr/bin/env python3
"""
新增一個 Blog 到 Nebula Search。

用法：
    python3 add_blog.py <網域> <RSS網址>

範例：
    python3 add_blog.py carrot.tw https://carrot.tw/index.xml

這支腳本會做兩件事：
    1. 把網域加進 blogroll_graph.json（永久保留，不會被 extract_rss.py 每小時覆蓋洗掉）
    2. 把網域 + feed 網址加進 rss_feeds.json（讓下一次 rss_fetcher.py 立刻抓得到）

不會自動重啟服務或立刻抓取；請自行執行：
    docker exec nebula_search_web-updater-1 sh -c "cd /app && python rss_fetcher.py"
"""

import json
import sys
from pathlib import Path
from datetime import datetime

GRAPH_PATH = "blogroll_graph.json"
FEEDS_PATH = "rss_feeds.json"


def backup(path: str):
    p = Path(path)
    if not p.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = p.with_name(f"{p.name}.bak-{stamp}")
    backup_path.write_bytes(p.read_bytes())
    print(f"  備份: {backup_path}")


def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_to_graph(domain: str) -> bool:
    graph = load_json(GRAPH_PATH, {})
    if domain in graph:
        print(f"[blogroll_graph.json] {domain} 已存在，跳過")
        return False
    backup(GRAPH_PATH)
    graph[domain] = {"blogroll_url": "", "links_to": []}
    save_json(GRAPH_PATH, graph)
    print(f"[blogroll_graph.json] 已新增 {domain}（共 {len(graph)} 個節點）")
    return True


def add_to_feeds(domain: str, feed_url: str) -> bool:
    feeds = load_json(FEEDS_PATH, [])
    if any(f.get("domain") == domain for f in feeds):
        print(f"[rss_feeds.json] {domain} 已存在，跳過")
        return False
    backup(FEEDS_PATH)
    feeds.append({"domain": domain, "feed_url": feed_url})
    save_json(FEEDS_PATH, feeds)
    print(f"[rss_feeds.json] 已新增 {domain} → {feed_url}（共 {len(feeds)} 筆）")
    return True


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    domain = sys.argv[1].strip()
    feed_url = sys.argv[2].strip()

    # 簡單防呆：domain 不該含 http:// 或路徑
    if domain.startswith("http://") or domain.startswith("https://"):
        print(f"錯誤：網域不該包含 http(s)://，你是不是把網域跟 RSS 網址寫反了？")
        print(f"  網域範例: carrot.tw")
        print(f"  RSS 網址範例: https://carrot.tw/index.xml")
        sys.exit(1)

    if "/" in domain:
        print(f"錯誤：網域不該包含斜線或路徑，只能是主機名稱")
        print(f"  你輸入的網域: {domain}")
        print(f"  網域應該只到主機名稱，例如: itsxiaobai.codeberg.page")
        print(f"  路徑請放在 RSS 網址裡: https://itsxiaobai.codeberg.page/pages/index.xml")
        sys.exit(1)

    if not (feed_url.startswith("http://") or feed_url.startswith("https://")):
        print(f"錯誤：RSS 網址必須以 http:// 或 https:// 開頭")
        sys.exit(1)

    print(f"新增 Blog：{domain}")
    print(f"RSS 網址：{feed_url}")
    print()

    changed_graph = add_to_graph(domain)
    changed_feeds = add_to_feeds(domain, feed_url)

    print()
    if changed_graph or changed_feeds:
        print("完成。要立刻抓取這個新 Blog，執行：")
        print('  docker exec nebula_search_web-updater-1 sh -c "cd /app && python rss_fetcher.py"')
    else:
        print("沒有任何變更（該網域已經存在於兩個檔案中）。")


if __name__ == "__main__":
    main()
