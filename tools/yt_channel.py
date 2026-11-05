"""List a YouTube channel's videos (yt-dlp, flat) and try to fetch transcripts for those whose titles match keywords.
Usage: python yt_channel.py CHANNEL_URL OUTDIR "kw1|kw2|..." MAX"""
import json, re, subprocess, sys, os
url, out, kw, mx = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
os.makedirs(out, exist_ok=True)
vids = []
for tab in ("videos", "streams", "shorts"):
    r = subprocess.run(["yt-dlp", "--flat-playlist", "-J", url.rstrip("/") + "/" + tab], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        vids += [dict(id=e["id"], title=e.get("title"), views=e.get("view_count"), dur=e.get("duration"), tab=tab) for e in j.get("entries") or []]
    except Exception as e:  # noqa: BLE001
        open(f"{out}/list_{tab}.err", "w").write(r.stderr[-3000:])
json.dump(vids, open(f"{out}/videos.json", "w"), indent=0, ensure_ascii=False)
print("videos", len(vids))
pick = [v for v in vids if v["title"] and re.search(kw, v["title"], re.I)][:mx]
print("matching", len(pick))
from youtube_transcript_api import YouTubeTranscriptApi
api = YouTubeTranscriptApi()
ok = 0
for v in pick:
    try:
        t = api.fetch(v["id"], languages=["hi", "en", "en-IN"])
        open(f"{out}/{v['id']}.txt", "w").write(v["title"] + "\n\n" + "\n".join(s.text for s in t)); ok += 1; continue
    except Exception as e:  # noqa: BLE001
        err = str(e)[:300]
    r = subprocess.run(["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "hi,en.*", "--sub-format", "vtt",
                        "-o", f"{out}/%(id)s.%(ext)s", f"https://www.youtube.com/watch?v={v['id']}"], capture_output=True, text=True)
    if any(f.startswith(v["id"]) and f.endswith(".vtt") for f in os.listdir(out)):
        ok += 1
    else:
        open(f"{out}/{v['id']}.err", "w").write(err + "\n---\n" + r.stderr[-800:])
print("transcripts", ok)
