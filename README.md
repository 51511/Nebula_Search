
Nebula Blog 搜尋引擎
==============================
(有點Bug?)- 2026/05/07

把 Nebula 產生的 json 當作「星圖」，並同步抓取所有 RSS/Atom Feed，建立中文Blog圈搜尋引擎。
![picture](https://i.meee.com.tw/dTjJFIP.png)

依賴：
    pip install aiohttp feedparser

用法：
- 先改掉extract_rss.py裡面用Nubla產生出來的blogroll_graph.json路徑或將檔案放入此專案中
- 啟用爬蟲
```
python extract_rss.py --input blogroll_graph.json --output rss_feeds.json
```
- 抓取所有 RSS
```
python rss_fetcher.py
```
- 指定來源與輸出
```
python rss_fetcher.py --feeds rss_feeds.json --output articles.json
```
- 搜尋
```
python rss_fetcher.py --search "我與貍奴不出門"
python rss_fetcher.py --search "生活" --limit 20
```

第一步：找出每個 domain 的 RSS feed

extract_rss.py 會對每個 domain 嘗試自動偵測 RSS/Atom feed 的位置——先看首頁的 <link rel="alternate"> 標籤，找不到就逐一試常見路徑（/feed、/rss.xml、/?feed=rss2 等）。結果存進 rss_feeds.json。

第二步：抓取所有文章、建立搜尋索引
bashpython rss_fetcher.py
這步會讀取 rss_feeds.json，非同步抓取所有 feed，解析每篇文章的標題、摘要、作者、標籤、發布時間，然後寫入 SQLite 資料庫（nebula.db），同時輸出一份 articles.json。SQLite 裡啟用了 FTS5 全文搜尋，用 trigram tokenizer，中文也能搜。

第三步：搜尋
bashpython rss_fetcher.py --search "想搜的關鍵字"
python rss_fetcher.py --search "生活" --limit 20
直接查 FTS5 索引，結果按 BM25 相關性排序。短詞（不足三字）會自動 fallback 到 LIKE 搜尋，就是剛剛修的那個部分。
