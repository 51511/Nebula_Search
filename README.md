
Nebula Blog 搜尋引擎
==============================

不想自己部屬？[我已經部屬好了](https://nebula.xn--i2rt58ao7w.com/)（不過我不保證穩定）

把 Nebula 產生的 json 當作「星圖」，並同步抓取所有 RSS/Atom Feed，建立中文Blog圈搜尋引擎。
![picture](https://i.meee.com.tw/dTjJFIP.png)

**預設已經不提供資料庫！請自行跑Nebula獲取**

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

# Docker 部署WEB
```
docker compose up -d --build
```

會啟動兩個服務：
- `web`：搜尋介面，預設監聽 1999 port
- `updater`：cron 排程，每小時自動重新抓取所有 RSS Feed 並更新資料庫

# 授權

見 LICENSE。
