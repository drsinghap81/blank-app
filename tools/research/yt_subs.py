"""Subscriber / video counts of the creators to pitch (21 Nov 2026)."""
import re

import requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept-Language": "en"}
C = {"Vijay Thakkar": "UCHvscyzKoKxhLcaz1LQ6mHg", "Finance With Sunil (Sunil Gurjar)": "UC_YjyLcl8jun5zetc70XWmA",
     "Siddharth Bhanushali": "UCoi7mlbUebBpQmDtB3L557A", "Bharat Jhunjhunwala": "UCiyqiag20iAsOwL9SHJMQ4g"}
for n, c in C.items():
    t = requests.get(f"https://www.youtube.com/channel/{c}/about", headers=H, timeout=30).text
    subs = re.findall(r'"(?:subscriberCountText|metadataParts)"[^}]*?"content":"([^"]*subscriber[^"]*)"', t) or re.findall(r'([\d.,]+[KMk]?\s*subscribers)', t)
    vids = re.findall(r'([\d.,]+[KM]?\s*videos)', t)
    print("R|", n, "| subs", list(dict.fromkeys(subs))[:2], "| videos", list(dict.fromkeys(vids))[:1], flush=True)
