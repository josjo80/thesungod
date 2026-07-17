"""Manuscript -> narration script JSON (single-narrator science prose).

Reads a chapter markdown file (read-only) and emits an ordered list of
segments for a single narrator. Unlike a novel, there is no dialogue casting;
the work here is turning book markdown into clean spoken text:

  * `#`/`##` section headings become their own `heading` segments (and start a
    new "scene", so the stitcher inserts a pause around them).
  * `> ...` blockquotes (the "FOR THE CURIOUS" sidebars) become `sidebar`
    segments, optionally prefaced with a spoken cue and title-cased so the
    narrator doesn't spell out SHOUTED labels.
  * Inline markdown (`**bold**`, `*italic*`, `` `code` ``, `[links](url)`) is
    flattened to plain text.
  * Trailing editorial notes (e.g. the "*Sources to firm up...*" line) are
    dropped so they are never narrated.

    python src/segment.py                          # all chapters (settings glob)
    python src/segment.py ../chapters/ch10_*.md    # one chapter

Output: script/<chapter>.json  (version-controlled, human-editable)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS_DIR = ROOT.parent / "chapters"
SCRIPT_DIR = ROOT / "script"
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
SEG = SETTINGS["segmentation"]

EDITORIAL_RES = [re.compile(p, re.IGNORECASE) for p in SEG["editorial_note_patterns"]]


SUPERSCRIPTS = {"²": " squared", "³": " cubed", "⁴": " to the fourth"}


def clean_inline(s: str) -> str:
    """Flatten inline markdown to spoken plain text."""
    for sup, word in SUPERSCRIPTS.items():             # r³ -> "r cubed"
        s = s.replace(sup, word)
    s = re.sub(r"`([^`]*)`", r"\1", s)                 # inline code
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)      # [text](url) -> text
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)           # **bold**
    s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", s)  # *italic*
    s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", s)     # _italic_
    s = re.sub(r"[*_`#>]+", "", s)                      # any stray markers
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_editorial(text: str) -> bool:
    return SEG["drop_editorial_notes"] and any(r.match(text) for r in EDITORIAL_RES)


def render_sidebar(para: str) -> str:
    """Strip blockquote markers and turn the box into spoken text.

    The first line is the box label (e.g. "FOR THE CURIOUS — Why bigger cells
    starve"). When `sidebar_label_as_cue` is set it becomes the spoken signpost,
    sentence-cased so a shouted tag isn't spelled out and its em-dash read as a
    sentence break: "For the curious. Why bigger cells starve." The remaining
    lines follow as ordinary narration. `sidebar_cue`, if non-empty, is prefixed.
    """
    lines = [clean_inline(re.sub(r"^\s*>\s?", "", ln))
             for ln in para.splitlines()]
    lines = [ln for ln in lines if ln]

    parts: list[str] = []
    cue = SEG.get("sidebar_cue", "").strip()
    if cue:
        parts.append(cue if cue.endswith((".", "!", "?")) else cue + ".")

    if lines and SEG.get("sidebar_label_as_cue"):
        label, *rest = lines
        for chunk in re.split(r"\s*[—–]\s*|\s+-\s+", label):  # split on dashes
            chunk = chunk.strip()
            if not chunk:
                continue
            # Sentence-case an ALL-CAPS tag (FOR THE CURIOUS -> For the curious).
            if chunk.replace(" ", "").isupper():
                chunk = chunk.capitalize()
            parts.append(chunk if chunk.endswith((".", "!", "?")) else chunk + ".")
        lines = rest

    parts.append(" ".join(lines))
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def segment_chapter(path: Path) -> dict:
    raw = path.read_text().strip()
    lines = raw.splitlines()

    title = path.stem
    if lines and lines[0].startswith("#"):
        title = clean_inline(lines[0])
        lines = lines[1:]

    # Split into blocks on blank lines; a run of `>` lines stays one block.
    body = "\n".join(lines).strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]

    segments = []
    seg_id = 0
    scene = 0
    for block in blocks:
        if re.fullmatch(r"-{3,}", block):   # horizontal rule / scene break
            scene += 1
            continue

        is_heading = block.startswith("#")
        is_sidebar = all(ln.lstrip().startswith(">") for ln in block.splitlines())

        if is_heading:
            text, seg_type = clean_inline(block), "heading"
            scene += 1                       # heading opens a new section/scene
        elif is_sidebar:
            text, seg_type = render_sidebar(block), "sidebar"
            scene += 1                       # sidebar sits in its own scene
        else:
            text, seg_type = clean_inline(block), "prose"

        if not text or is_editorial(text):
            continue

        segments.append({
            "id": seg_id,
            "scene": scene,
            "type": seg_type,
            "speaker": "narrator",
            "text": text,
            "emotion_tags": [],
        })
        seg_id += 1
        if seg_type == "sidebar":
            scene += 1                       # prose after a sidebar resumes fresh

    return {"chapter": path.stem, "title": title, "segments": segments}


def chapter_targets() -> list[Path]:
    return sorted(CHAPTERS_DIR.glob(SEG["chapter_glob"]))


def main(argv: list[str]) -> int:
    SCRIPT_DIR.mkdir(exist_ok=True)
    targets = [Path(a) for a in argv] if argv else chapter_targets()
    if not targets:
        print(f"No chapters found in {CHAPTERS_DIR} matching {SEG['chapter_glob']}")
        return 1

    for path in targets:
        result = segment_chapter(path)
        dest = SCRIPT_DIR / f"{path.stem}.json"
        dest.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        counts = {}
        for s in result["segments"]:
            counts[s["type"]] = counts.get(s["type"], 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"{path.name}: {len(result['segments'])} segments ({summary}) -> {dest.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
