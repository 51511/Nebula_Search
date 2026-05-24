
Nebula Blog 搜尋引擎
==============================

[網頁版！]((https://nebula.quickconnect.qzz.io/))

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
