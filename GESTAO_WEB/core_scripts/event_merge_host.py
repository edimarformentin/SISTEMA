#!/usr/bin/env python3
import os, re, json, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(os.environ.get("FRIGATE_BASE", "/home/edimar/SISTEMA/FRIGATE"))
MERGE_WINDOW = int(os.environ.get("MERGE_WINDOW_SEC", "30"))
MERGE_MIN = int(os.environ.get("MERGE_MIN_COUNT", "2"))
MERGE_LIMIT = int(os.environ.get("MERGE_LIMIT", "5"))
VERBOSE = int(os.environ.get("MERGE_VERBOSE", "1"))
KEEP_ORIG = int(os.environ.get("MERGE_KEEP_ORIG", "1"))

DATE_RE = re.compile(r"(?P<date>\d{8})[_\-\.](?P<time>\d{6})")

def parse_start_from_name(p: Path):
    m = DATE_RE.search(p.name)
    if not m: return None
    return datetime.strptime(m.group("date")+m.group("time"), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

def ffprobe_duration(f: Path) -> float:
    try:
        out = subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(f)], text=True).strip()
        return float(out)
    except Exception: return 0.0

def build_groups(files):
    groups, cur = [], []
    for item in files:
        if not cur: cur = [item]; continue
        prev = cur[-1]
        gap = (item["start"] - prev["end"]).total_seconds()
        if gap <= MERGE_WINDOW: cur.append(item)
        else:
            if len(cur) >= MERGE_MIN: groups.append(cur)
            cur = [item]
    if cur and len(cur) >= MERGE_MIN: groups.append(cur)
    return groups

def concat_group(cam_dir: Path, group):
    first, last = group[0], group[-1]
    start_s, end_s = first["start"].strftime("%Y%m%d_%H%M%S"), last["end"].strftime("%Y%m%d_%H%M%S")
    out_mp4 = cam_dir / f"{start_s}__{end_s}_merged.mp4"
    if out_mp4.exists(): return False
    tmp_dir = cam_dir / ".tmp_merge"; tmp_dir.mkdir(parents=True, exist_ok=True)
    files_txt = tmp_dir / "files.txt"
    with files_txt.open("w") as f:
        for it in group: f.write(f"file '{it['path']}'\n")
    concat_out = tmp_dir / "concat.mp4"
    subprocess.check_call(["ffmpeg","-hide_banner","-nostdin","-y","-f","concat","-safe","0","-i",str(files_txt),"-c","copy",str(concat_out)])
    concat_out.replace(out_mp4)
    meta = {"camera_dir": str(cam_dir), "output": str(out_mp4), "start_iso": first["start"].isoformat(), "end_iso": last["end"].isoformat(), "count": len(group), "sources": [str(it["path"]) for it in group]}
    out_mp4.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    if not KEEP_ORIG:
        for it in group:
            try: Path(it["path"]).unlink(missing_ok=True); Path(it["path"]).with_suffix(".json").unlink(missing_ok=True)
            except Exception: pass
    try: tmp_dir.rmdir()
    except Exception: pass
    if VERBOSE: print(f"[ok] merged: {out_mp4} (n={len(group)})")
    return True

def main():
    if not BASE.exists(): return
    processed_groups = 0
    for uid_dir in sorted([d for d in BASE.iterdir() if d.is_dir()]):
        events_dir = uid_dir / "events"
        if not events_dir.exists(): continue
        for cam_dir in sorted([d for d in events_dir.iterdir() if d.is_dir()]):
            mp4s = sorted([p for p in cam_dir.glob("*.mp4") if "_merged" not in p.name])
            if not mp4s: continue
            items = []
            for p in mp4s:
                st = parse_start_from_name(p) or datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                dur = ffprobe_duration(p)
                end = st if dur <= 0 else (st + timedelta(seconds=dur))
                items.append({"path": str(p), "start": st, "end": end})
            items.sort(key=lambda x: x["start"])
            groups = build_groups(items)
            for g in groups:
                if processed_groups >= MERGE_LIMIT: return
                if concat_group(cam_dir, g): processed_groups += 1

if __name__ == "__main__": main()
