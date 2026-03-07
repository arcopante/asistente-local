"""
transcriber.py — Transcripcion de audio con faster-whisper (local, sin API externa)

Modelos disponibles por tamanio/velocidad:
  tiny, base, small, medium, large-v2, large-v3
Configurable con WHISPER_MODEL en start.sh (por defecto: base)
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

# El modelo se carga una sola vez y se reutiliza
_model = None
_model_name = None


def _get_model():
    """Carga el modelo Whisper la primera vez y lo cachea."""
    global _model, _model_name
    model_name = os.environ.get("WHISPER_MODEL", "base")
    if _model is None or _model_name != model_name:
        try:
            from faster_whisper import WhisperModel
            device = os.environ.get("WHISPER_DEVICE", "cpu")
            compute = "int8" if device == "cpu" else "float16"
            _model = WhisperModel(model_name, device=device, compute_type=compute)
            _model_name = model_name
        except ImportError:
            raise RuntimeError(
                "faster-whisper no esta instalado. Ejecuta: pip install faster-whisper"
            )
    return _model


def transcribe(audio_path: str, language: Optional[str] = None) -> str:
    """
    Transcribe un fichero de audio y devuelve el texto.
    audio_path : ruta al fichero de audio (ogg, mp3, wav, m4a, etc.)
    language   : codigo de idioma ('es', 'en', ...) o None para autodetectar
    """
    model = _get_model()
    lang = language or os.environ.get("WHISPER_LANGUAGE") or None

    segments, info = model.transcribe(
        audio_path,
        language=lang,
        beam_size=5,
        vad_filter=True,           # filtra silencios automaticamente
        vad_parameters={"min_silence_duration_ms": 500},
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text


def transcribe_bytes(audio_bytes: bytes, suffix: str = ".ogg") -> str:
    """
    Transcribe audio desde bytes (util para ficheros descargados de Telegram).
    Escribe a un fichero temporal, transcribe y lo borra.
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        return transcribe(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def is_available() -> bool:
    """Comprueba si faster-whisper esta instalado."""
    try:
        import faster_whisper  # noqa
        return True
    except ImportError:
        return False
