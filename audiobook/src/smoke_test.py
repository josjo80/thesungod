"""Smoke test: confirm the API key works and eleven_v3 is reachable.

Generates one short line with the narrator voice and saves it to
output/smoke_test.mp3. Run this once after putting your ROTATED key in .env.

    python src/smoke_test.py
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())


def main() -> int:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key or api_key.startswith("sk_your_"):
        print("ERROR: set ELEVENLABS_API_KEY in audiobook/.env (see .env.example).")
        return 1

    client = ElevenLabs(api_key=api_key)
    line = ("[warm] For roughly the first half of its history, life on Earth "
            "was a resounding success and a crashing bore.")

    print(f"Requesting model={SETTINGS['model_id']} voice={SETTINGS['narrator_voice_id']} ...")
    try:
        audio = client.text_to_speech.convert(
            voice_id=SETTINGS["narrator_voice_id"],
            model_id=SETTINGS["model_id"],
            output_format=SETTINGS["output_format"],
            text=line,
        )
    except Exception as exc:  # noqa: BLE001 — surface the real API error verbatim
        print(f"ERROR calling ElevenLabs: {exc}")
        print("If this mentions model access, your account may need v3 API access enabled.")
        return 2

    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    dest = out / "smoke_test.mp3"
    with open(dest, "wb") as fh:
        for chunk in audio:
            fh.write(chunk)

    size = dest.stat().st_size
    print(f"OK — wrote {dest} ({size} bytes). v3 access confirmed." if size > 0
          else f"WARNING — wrote {dest} but it is empty.")
    return 0 if size > 0 else 3


if __name__ == "__main__":
    sys.exit(main())
