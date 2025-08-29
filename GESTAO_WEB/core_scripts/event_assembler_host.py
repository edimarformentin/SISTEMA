#!/usr/bin/env python3
import os, re, json, shutil, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

DEFAULT_PRE = int(os.environ.get("EVENT_PRESECONDS", "12"))
DEFAULT_POST = int(os.environ.get("EVENT_POSTSECONDS", "12"))
EXTRA_PAD = 2
VERBOSE = int(os.environ.get("EVENT_VERBOSE", "1"))

DEFAULT_BASE_CANDIDATES = [
    "/home/edimar/SISTEMA/FRIGATE",
    "/home/edimar/FRIGATE",
    "/FRIGATE",
]

DATE_RE = re.compile(r"(?P<date>\d{8})[_\-\.](?P<time>\d{6})")

def log(*a):
    if VERBOSE: print(*a, flush=True)

def parse_snapshot_time(p: Path) -> datetime:
    m = DATE_RE.search(p.name)
    if m:
        return datetime.strptime(m.group("date")+m.group("time"), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

def run_ffmpeg(args):
    cmd = ["ffmpeg","-hide_banner","-nostdin","-y"] + args
    log("[ffmpeg]", " ".join(cmd))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout

def escape_path(p: Path) -> str:
    return str(p).replace("'", r"'\''")

def pick_base_dir(cli_base: str|None) -> Path:
    if cli_base and Path(cli_base).exists(): return Path(cli_base)
    envb = os.environ.get("FRIGATE_BASE")
    if envb and Path(envb).exists(): return Path(envb)
    for cand in DEFAULT_BASE_CANDIDATES:
        if Path(cand).exists(): return Path(cand)
    raise SystemExit("[ERRO] Não encontrei a base FRIGATE. Defina FRIGATE_BASE ou use --base.")

def recordings_roots(uid_dir: Path):
    return [p for p in [uid_dir / "media" / "recordings", uid_dir / "media" / "frigate" / "recordings"] if p.exists()]

def recordings_dirs_for_range(uid_dir: Path, camera: str, t0: datetime, t1: datetime):
    roots = recordings_roots(uid_dir)
    out = []
    if not roots: return out
    cur = datetime(t0.year, t0.month, t0.day, t0.hour, tzinfo=timezone.utc)
    end = datetime(t1.year, t1.month, t1.day, t1.hour, tzinfo=timezone.utc)
    while cur <= end:
        day, hour = cur.strftime("%Y-%m-%d"), cur.strftime("%H")
        for root in roots:
            d = root / day / hour / camera
            if d.exists(): out.append(d)
        cur += timedelta(hours=1)
    return out

def select_segments(dirs, t0: datetime, t1: datetime):
    segs = []
    for d in dirs: segs.extend(sorted(d.glob("*.mp4")))
    segs.sort(key=lambda p: (p.parent.as_posix(), p.name, p.stat().st_mtime))
    return segs

def build_concat_and_trim(segments, out_final: Path, t_start: datetime, t_end: datetime):
    if not segments: return False, "sem segmentos"
    tmp_dir = out_final.parent / ".tmp_event_build"; tmp_dir.mkdir(parents=True, exist_ok=True)
    concat_list = tmp_dir / "files.txt"
    with concat_list.open("w") as f:
        for seg in segments: f.write(f"file '{escape_path(seg)}'\n")
    tmp_concat = tmp_dir / "concat.mp4"
    rc, out = run_ffmpeg(["-f","concat","-safe","0","-i", str(concat_list), "-c","copy", str(tmp_concat)])
    if rc != 0 or not tmp_concat.exists(): return False, f"concat falhou: {out}"
    first_seg_start = datetime.fromtimestamp(segments[0].stat().st_mtime, tz=timezone.utc) - timedelta(seconds=EXTRA_PAD)
    ss = max(0.0, (t_start - first_seg_start).total_seconds())
    dur = max(0.1, (t_end - t_start).total_seconds())
    tmp_out = tmp_dir / "tmp_cut_copy.mp4"
    rc, out = run_ffmpeg(["-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(tmp_concat), "-c","copy", str(tmp_out)])
    if rc != 0 or not tmp_out.exists() or tmp_out.stat().st_size < 2000:
        tmp_out2 = tmp_dir / "tmp_cut_reenc.mp4"
        rc, out = run_ffmpeg(["-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(tmp_concat), "-c:v","libx264","-preset","veryfast","-crf","20", "-c:a","aac","-movflags","+faststart", str(tmp_out2)])
        if rc != 0 or not tmp_out2.exists(): return False, f"trim reencode falhou: {out}"
        shutil.move(str(tmp_out2), str(out_final))
    else:
        shutil.move(str(tmp_out), str(out_final))
    try:
        shutil.rmtree(tmp_dir)
    except Exception: pass
    return True, "ok"

def find_snapshots(base: Path):
    for uid_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
        ev = uid_dir / "events"
        if not ev.exists(): continue
        for cam_dir in sorted([p for p in ev.iterdir() if p.is_dir()]):
            for jpg in sorted(cam_dir.glob("*.jpg")):
                yield uid_dir, cam_dir.name, jpg

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--base"); ap.add_argument("--pre", type=int, default=DEFAULT_PRE); ap.add_argument("--post", type=int, default=DEFAULT_POST); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--verbose", type=int, default=0)
    args = ap.parse_args()
    global VERBOSE; VERBOSE = int(args.verbose)
    base = pick_base_dir(args.base)
    log(f"[info] base: {base}")
    cnt = 0
    for uid_dir, camera, jpg in find_snapshots(base):
        out_mp4 = jpg.with_suffix('.mp4'); out_json = jpg.with_suffix('.json')
        if out_mp4.exists(): continue
        snap_ts = parse_snapshot_time(jpg)
        t_start, t_end = snap_ts - timedelta(seconds=args.pre), snap_ts + timedelta(seconds=args.post)
        dirs = recordings_dirs_for_range(uid_dir, camera, t_start, t_end)
        if not dirs: continue
        segs = select_segments(dirs, t_start, t_end)
        if not segs: continue
        ok, msg = build_concat_and_trim(segs, out_mp4, t_start, t_end)
        if not ok: log(f"[ERRO] {uid_dir.name}/{camera} {jpg.name}: {msg}"); continue
        meta = {"unique_id": uid_dir.name, "camera": camera, "snapshot": str(jpg), "video": str(out_mp4), "created_utc": datetime.now(timezone.utc).isoformat(), "snapshot_ts_utc": snap_ts.isoformat(), "start_utc": t_start.isoformat(), "end_utc": t_end.isoformat(), "pre_s": args.pre, "post_s": args.post}
        with open(out_json, "w") as f: json.dump(meta, f, ensure_ascii=False, indent=2)
        log(f"[ok] gerado: {out_mp4}")
        cnt += 1
        if args.limit and cnt >= args.limit: break
    log(f"[fim] processados: {cnt}")

if __name__ == "__main__": main()
