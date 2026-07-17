# The Sun God — Audiobook Pipeline

Turns the `../chapters/*.md` manuscript into a single-narrator audiobook using
ElevenLabs v3. **Reads the manuscript read-only** — it never modifies your
chapter files.

## Pipeline

```
../chapters/ch*.md  --segment-->  script/*.json  --generate-->  audio/segments/  --stitch-->  output/the-sun-god.m4b + output/chapters/*.mp3
```

| Stage | Script | What it does |
|-------|--------|--------------|
| Segment  | `src/segment.py`  | Markdown -> spoken segments (headings, sidebars, prose); drops editorial notes |
| Generate | `src/generate.py` | Render each block with the narrator voice; cache by content hash |
| Stitch   | `src/stitch.py`   | Concatenate with type-aware pauses, loudness-normalize, build M4B |

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then paste your ROTATED ElevenLabs key
```

Requires `ffmpeg` on PATH (`brew install ffmpeg`).

## Run

```bash
.venv/bin/python src/smoke_test.py                        # confirm v3 access (1 clip)
.venv/bin/python src/segment.py                           # build script/*.json
.venv/bin/python src/generate.py --dry-run                # cost estimate, no API calls
.venv/bin/python src/generate.py ch10_the_great_bottleneck  # render one chapter
.venv/bin/python src/stitch.py                            # assemble the audiobook
```

## Config

`config/settings.json` controls everything:

- **model / voice / output** — `eleven_v3`, narrator `voice_id`, mp3 format.
- **segmentation** — chapter glob, sidebar handling (`sidebar_cue`,
  `sidebar_title_case`), and `editorial_note_patterns` (paragraphs matching
  these — e.g. the "Sources to firm up..." note — are never narrated).
- **assembly** — loudness target and the silence gaps used between blocks,
  around headings/sidebars, between sections, and between chapters.

`config/voices.json` holds the single narrator voice.

## How the manuscript is read

- `#`/`##` headings become spoken section titles with a pause around them.
- `> ...` blockquotes (the "FOR THE CURIOUS" boxes) are read as sidebars,
  prefaced with a short spoken cue and title-cased so shouted labels aren't
  spelled out. Adjust or silence the cue in `settings.json`.
- Inline markdown (`**bold**`, `*italic*`, `` `code` ``, links) is flattened.
- The trailing editorial "Sources..." note in Ch. 10 is dropped automatically.

Everything downstream of the manuscript flows through `script/*.json`, which is
version-controlled and hand-editable — tweak wording, add v3 `emotion_tags`, or
fix a sidebar there and re-run `generate.py`/`stitch.py`.

## Security

`.env` holds your API key and is git-ignored. **Rotate the key shared in chat.**
`audio/`, `output/`, and `.cache/` are git-ignored (large binaries);
`script/*.json` is version-controlled.
