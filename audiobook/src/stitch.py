"""audio segments -> per-chapter MP3 + full M4B audiobook.

Concatenates each chapter's blocks with type-aware pauses (bigger silences
around section headings and sidebars), loudness-normalizes, then builds a
chaptered .m4b with metadata. Requires ffmpeg on PATH.

    python src/stitch.py            # build everything (per settings.outputs)
    python src/stitch.py ch10_the_great_bottleneck   # one chapter MP3 only
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
SCRIPT_DIR = ROOT / "script"
SEG_DIR = ROOT / "audio" / "segments"
OUT = ROOT / "output"
CH_MP3 = OUT / "chapters"
BOOK_SLUG = re.sub(r"[^a-z0-9]+", "-", SETTINGS["assembly"]["book_title"].lower()).strip("-")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _chapter_num(stem: str) -> int:
    m = re.search(r"(\d+)", stem)
    return int(m.group(1)) if m else 0


def _gap_ms(prev: dict, nxt: dict | None, a: dict) -> int:
    """Pause after a block, largest around headings and sidebars."""
    if nxt is None:
        return 0
    if nxt["type"] == "heading" or prev["type"] == "heading":
        return a["heading_gap_ms"]
    if nxt["type"] == "sidebar" or prev["type"] == "sidebar":
        return a["sidebar_gap_ms"]
    if nxt["scene"] != prev["scene"]:
        return a["scene_gap_ms"]
    return a["block_gap_ms"]   # continuation of one prose run split by the cap


def build_chapter_mp3(chapter: str) -> Path:
    seg_dir = SEG_DIR / chapter
    manifest = seg_dir / "blocks.json"
    if manifest.exists():
        blocks = json.loads(manifest.read_text())["blocks"]
    else:  # fallback: treat each clip as its own block with a uniform gap
        blocks = [{"file": c.name, "type": "prose", "scene": i}
                  for i, c in enumerate(sorted(seg_dir.glob("*.mp3")))]
    if not blocks:
        raise FileNotFoundError(f"No audio for {chapter}. Run src/generate.py.")

    a = SETTINGS["assembly"]
    CH_MP3.mkdir(parents=True, exist_ok=True)
    pad_dir = seg_dir / "_padded"
    pad_dir.mkdir(exist_ok=True)

    # Pad each block with the appropriate trailing silence, uniformly re-encoded.
    padded = []
    for i, blk in enumerate(blocks):
        src = seg_dir / blk["file"]
        gap = _gap_ms(blk, blocks[i + 1] if i + 1 < len(blocks) else None, a)
        out = pad_dir / f"{i:04d}.mp3"
        af = ["-af", f"apad=pad_dur={gap / 1000}"] if gap > 0 else []
        _run(["ffmpeg", "-y", "-i", str(src), *af,
              "-c:a", "libmp3lame", "-q:a", "2", str(out)])
        padded.append(out)

    concat_list = seg_dir / "_concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in padded))
    dest = CH_MP3 / f"{chapter}.mp3"
    filt = (f"loudnorm=I={a['target_lufs']}:TP={a['true_peak_db']}"
            if a["loudness_normalize"] else "anull")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
          "-af", filt, "-c:a", "libmp3lame", "-q:a", "2", str(dest)])

    concat_list.unlink(missing_ok=True)
    for p in padded:
        p.unlink(missing_ok=True)
    pad_dir.rmdir()
    print(f"  {chapter} -> {dest.relative_to(ROOT)} ({len(blocks)} blocks)")
    return dest


def build_m4b(chapter_mp3s: list[Path], name: str) -> None:
    a = SETTINGS["assembly"]
    OUT.mkdir(exist_ok=True)

    meta = [";FFMETADATA1", f"title={a['book_title']}", f"artist={a['author']}"]
    list_file = OUT / "_m4b_concat.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in chapter_mp3s))

    start_ms = 0
    for p in chapter_mp3s:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
        dur_ms = int(float(out.stdout.strip()) * 1000)
        title = json.loads((SCRIPT_DIR / f"{p.stem}.json").read_text())["title"]
        meta += ["[CHAPTER]", "TIMEBASE=1/1000",
                 f"START={start_ms}", f"END={start_ms + dur_ms}", f"title={title}"]
        start_ms += dur_ms + a["chapter_gap_ms"]

    meta_file = OUT / "_chapters.txt"
    meta_file.write_text("\n".join(meta) + "\n")

    dest = OUT / name
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
          "-i", str(meta_file), "-map_metadata", "1",
          "-c:a", "aac", "-b:a", "128k", str(dest)])
    list_file.unlink(missing_ok=True)
    meta_file.unlink(missing_ok=True)
    print(f"M4B -> {dest.relative_to(ROOT)}")


def main(argv: list[str]) -> int:
    make_m4b = "--m4b" in argv
    chapters = [a for a in argv if not a.startswith("--")]
    all_scripts = sorted((p.stem for p in SCRIPT_DIR.glob("*.json")), key=_chapter_num)
    if not chapters:  # no chapters listed -> whole book, honoring settings.outputs
        chapters = all_scripts
        make_m4b = make_m4b or "m4b" in SETTINGS["assembly"]["outputs"]

    mp3s = [build_chapter_mp3(ch) for ch in chapters]
    if make_m4b:
        nums = [_chapter_num(c) for c in chapters]
        full = len(chapters) == len(all_scripts)
        name = f"{BOOK_SLUG}.m4b" if full else f"{BOOK_SLUG}_ch{nums[0]}-{nums[-1]}.m4b"
        build_m4b(mp3s, name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
