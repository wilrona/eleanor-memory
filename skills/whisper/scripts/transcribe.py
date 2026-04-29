#!/usr/bin/env python3.12
"""
Whisper transcription script for Hermes Agent.
Usage: python3.12 transcribe.py <audio_file> [model] [language]
"""
import sys
import whisper


def transcribe(audio_path: str, model_name: str = "base", language: str = "fr") -> dict:
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, language=language)
    return {
        "text": result["text"].strip(),
        "language": result.get("language"),
        "segments": [
            {
                "start": round(seg["start"], 1),
                "end": round(seg["end"], 1),
                "text": seg["text"].strip(),
            }
            for seg in result.get("segments", [])
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3.12 transcribe.py <audio_file> [model] [language]")
        sys.exit(1)

    audio_file = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else "base"
    language = sys.argv[3] if len(sys.argv) > 3 else "fr"

    result = transcribe(audio_file, model, language)
    print("=== TRANSCRIPTION ===")
    print(result["text"])
    print("=====================")
    print(f"Langue détectée: {result['language']}")
    print(f"Segments: {len(result['segments'])}")
