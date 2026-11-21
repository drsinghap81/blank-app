"""Probe (21 Nov 2026): can the runner list a creator's latest YouTube videos and read a transcript?"""
import re
import subprocess
import sys

import requests
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "youtube-transcript-api"], check=False)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept-Language": "en"}
NAMES = ["Vijay Thakkar", "Sunil Gurjar", "Siddharth Bhanushali", "Bharat Jhunjhunwala", "Sunil Minglani"]
for nm in NAMES:
    t = requests.get("https://www.youtube.com/results", params={"search_query": nm + " stock market"}, headers=H, timeout=30).text
    ch = re.findall(r'"channelId":"(UC[\w-]{22})"', t); vids = re.findall(r'"videoId":"([\w-]{11})"', t)
    owners = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', t)
    print("R|", nm, "| page", len(t), "| channels", list(dict.fromkeys(ch))[:3], "| owners", list(dict.fromkeys(owners))[:4], "| vids", list(dict.fromkeys(vids))[:3], flush=True)
    if ch:
        rss = requests.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": ch[0]}, headers=H, timeout=30).text
        titles = re.findall(r"<title>([^<]+)</title>", rss)[:4]; dates = re.findall(r"<published>([^<]+)</published>", rss)[:3]
        print("R|   rss", len(rss), titles, dates, flush=True)
    if vids:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            tr = api.fetch(vids[0], languages=["en", "hi", "en-IN"])
            txt = " ".join(s.text for s in tr)
            print("R|   transcript ok", len(txt), txt[:160], flush=True)
        except Exception as e:  # noqa: BLE001
            print("R|   transcript fail", type(e).__name__, str(e)[:160], flush=True)
