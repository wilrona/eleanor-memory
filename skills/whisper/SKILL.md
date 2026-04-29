---
name: whisper
description: "Transcribe audio files to text using OpenAI Whisper (local, free, offline speech-to-text)."
version: 1.0.0
author: Eleanor (assistant personnel)
license: MIT
metadata:
  hermes:
    tags: [audio, speech-to-text, transcription, whisper, voice]
    language: python3.12
---

# Whisper — Speech-to-Text Transcription

Transcrit des fichiers audio (.mp3, .wav, .ogg, .m4a, .webm, .mp4, etc.) en texte, localement avec OpenAI Whisper.

## Prérequis

- Python 3.12+ (pas l'env par défaut 3.11 — utiliser `/usr/bin/python3.12`)
- `openai-whisper` installé : `pip install openai-whisper --break-system-packages`
- `ffmpeg` installé (déjà présent sur le système)
- Modèle téléchargé automatiquement au premier usage

## Utilisation

```bash
# Transcription simple
python3.12 -c "
import whisper
model = whisper.load_model('base')  # 'tiny', 'base', 'small', 'medium', 'large'
result = model.transcribe('/chemin/vers/fichier.mp3')
print(result['text'])
"
```

## Modèles disponibles

| Modèle | Taille | Vitesse | Précision | Usage recommandé |
|--------|--------|---------|-----------|-----------------|
| `tiny` | ~39 Mo | Très rapide | Moyenne | Tests, quick checks |
| `base` | ~140 Mo | Rapide | Bonne | Usage quotidien |
| `small` | ~488 Mo | Moyen | Très bonne | Précision + vitesse |
| `medium` | ~1.5 Go | Lent | Excellente | Docs importants |
| `large` | ~2.9 Go | Très lent | Maximale | Cas critiques |

## Fonction de transcription prête à l'emploi

```python
import whisper

def transcribe(audio_path: str, model_name: str = "base", language: str = "fr") -> dict:
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, language=language)
    return {
        "text": result["text"].strip(),
        "language": result.get("language"),
        "segments": [
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip()
            }
            for seg in result.get("segments", [])
        ]
    }
```

## Intégration dans Hermes

Le module `execute_code` et les subagents utilisent Python 3.11 par défaut. Pour la transcription, appeler explicitement via terminal avec `python3.12` :

```bash
python3.12 - << 'EOF'
import whisper
model = whisper.load_model("base")
result = model.transcribe("/path/to/audio.ogg")
print(result["text"])
EOF
```

## Formats supportés

.mp3, .wav, .ogg, .m4a, .webm, .mp4, .mkv, .flac — tout ce que ffmpeg sait lire.

## Notes

- Transcription gratuite et离线 (aucun appel API externe)
- Fonctionne sans GPU (CPU only, plus lent)
- Pour de meilleures résultats : audio clair, sans musique de fond
