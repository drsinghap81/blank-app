"""yt-dlp metadata (description, chapters) + subtitles for given video ids. Usage: python yt_meta.py OUTDIR id1 id2 ..."""
import json, os, subprocess, sys
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
for v in sys.argv[2:]:
    u = f"https://www.youtube.com/watch?v={v}"
    r = subprocess.run(["yt-dlp", "--skip-download", "-J", u], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        json.dump(dict(id=v, title=j.get("title"), description=j.get("description"), chapters=j.get("chapters"),
                       upload_date=j.get("upload_date"), subs=list((j.get("subtitles") or {}).keys()),
                       auto=list((j.get("automatic_captions") or {}).keys())[:10]), open(f"{out}/{v}.json", "w"), ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        open(f"{out}/{v}.meta.err", "w").write(r.stderr[-1500:])
    r = subprocess.run(["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "hi,hi-orig,en,en-orig",
                        "--sub-format", "vtt", "-o", f"{out}/%(id)s.%(ext)s", u], capture_output=True, text=True)
    if not any(f.startswith(v) and f.endswith(".vtt") for f in os.listdir(out)):
        open(f"{out}/{v}.sub.err", "w").write(r.stderr[-1500:])
print(sorted(os.listdir(out)))
