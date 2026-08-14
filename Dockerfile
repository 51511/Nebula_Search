FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN apt-get update && apt-get install -y cron git git-lfs && git lfs install

RUN printf 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n0 * * * * root cd /app && python extract_rss.py >> /tmp/nebula-cron.log 2>&1 && python rss_fetcher.py >> /tmp/nebula-cron.log 2>&1\n' > /etc/cron.d/nebula \
    && chmod 0644 /etc/cron.d/nebula

CMD ["cron", "-f"]
