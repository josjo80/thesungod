"""script JSON -> audio blocks (ElevenLabs), single narrator.

Consecutive prose segments in the same section are merged into one continuous
*block* and generated in a single request, so the narrator keeps its pacing
instead of resetting every paragraph. Blocks break at section boundaries
(headings/sidebars each sit in their own "scene") or when a run would exceed the
model's per-request length cap.

Caches by block content hash so unchanged blocks are never re-billed, and writes
audio/segments/<chapter>/blocks.json for the stitcher (scene + type per block
drive the inter-block pauses).

    python src/generate.py                       # all chapters in script/
    python src/generate.py ch10_the_great_bottleneck
    python src/generate.py ch10_the_great_bottleneck --dry-run  # cost estimate
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
VOICES = json.loads((ROOT / "config" / "voices.json").read_text())
SCRIPT_DIR = ROOT / "script"
SEG_DIR = ROOT / "audio" / "segments"
CACHE = ROOT / ".cache"

# Keep a single request comfortably within eleven_v3's per-request text limit.
MAX_BLOCK_CHARS = 2500

NARRATOR_VID = VOICES["narrator"]["voice_id"]


def render_text(seg: dict) -> str:
    """Compose a segment's text, prepending any v3 emotion tags inline."""
    tags = "".join(f"[{t}]" for t in seg.get("emotion_tags", []))
    return f"{tags} {seg['text']}".strip() if tags else seg["text"]


def build_blocks(segs: list[dict]) -> list[dict]:
    """Merge consecutive same-scene prose segments into capped blocks."""
    blocks: list[dict] = []
    for seg in segs:
        text = render_text(seg)
        cur = blocks[-1] if blocks else None
        can_merge = (
            cur is not None
            and cur["scene"] == seg.get("scene", 0)
            and cur["type"] == seg.get("type", "prose")
            and len(cur["text"]) + 1 + len(text) <= MAX_BLOCK_CHARS
        )
        if can_merge:
            cur["text"] = f"{cur['text']} {text}"
        else:
            blocks.append({
                "id": len(blocks),
                "scene": seg.get("scene", 0),
                "type": seg.get("type", "prose"),
                "text": text,
            })
    return blocks


def block_hash(text: str) -> str:
    key = json.dumps({
        "text": text, "voice": NARRATOR_VID,
        "model": SETTINGS["model_id"], "settings": SETTINGS["voice_settings"],
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def generate_chapter(chapter: str, client, dry_run: bool) -> None:
    data = json.loads((SCRIPT_DIR / f"{chapter}.json").read_text())
    blocks = build_blocks(data["segments"])
    total_chars = sum(len(b["text"]) for b in blocks)
    print(f"{chapter}: {len(data['segments'])} segments -> {len(blocks)} blocks, ~{total_chars} chars")
    if dry_run:
        print(f"  [dry-run] would generate {len(blocks)} clips (~{total_chars} credits at 1/char)")
        return

    out_dir = SEG_DIR / chapter
    out_dir.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    for stale in out_dir.glob("*.mp3"):  # clear prior clips
        stale.unlink()

    manifest = {"chapter": chapter, "title": data.get("title", chapter), "blocks": []}
    for b in blocks:
        dest = out_dir / f"{b['id']:04d}.mp3"
        cached = CACHE / f"{block_hash(b['text'])}.mp3"
        if SETTINGS["generation"]["cache_by_content_hash"] and cached.exists():
            dest.write_bytes(cached.read_bytes())
        else:
            audio = client.text_to_speech.convert(
                voice_id=NARRATOR_VID,
                model_id=SETTINGS["model_id"],
                output_format=SETTINGS["output_format"],
                text=b["text"],
            )
            payload = b"".join(audio)
            dest.write_bytes(payload)
            if SETTINGS["generation"]["cache_by_content_hash"]:
                cached.write_bytes(payload)
            print(f"  [{b['id'] + 1}/{len(blocks)}] {b['type']:>7} ({len(b['text'])}c) -> {dest.name}")
        manifest["blocks"].append({
            "id": b["id"], "file": dest.name, "type": b["type"],
            "scene": b["scene"], "chars": len(b["text"]),
        })

    (out_dir / "blocks.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    names = [a for a in argv if not a.startswith("--")]
    chapters = names or [p.stem for p in sorted(SCRIPT_DIR.glob("*.json"))]
    if not chapters:
        print("No script JSON found. Run src/segment.py first.")
        return 1

    client = None
    if not dry_run:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key or api_key.startswith("sk_your_"):
            print("ERROR: set ELEVENLABS_API_KEY in audiobook/.env (see .env.example).")
            return 1
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=api_key)

    for ch in chapters:
        generate_chapter(ch, client, dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
