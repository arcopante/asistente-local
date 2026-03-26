"""
tts_engine.py — Sintesis de voz con clonacion usando Coqui XTTS-v2.

Convierte texto a audio WAV usando la voz de un fichero de muestra local.
Corre completamente en local, sin enviar datos a internet.

Variables de entorno relevantes (configuradas en start.sh):
  TTS_ENABLED        true | false  (por defecto: false)
  TTS_VOICE_SAMPLE   ruta al fichero WAV de muestra de voz (obligatorio)
  TTS_LANGUAGE       es | en | fr | ...  (por defecto: es)
  TTS_DEVICE         cpu | cuda  (por defecto: cpu)
"""

import os
import tempfile
import logging
import warnings

# Suprimir FutureWarning de torch.load en Coqui TTS (interno de la libreria)
warnings.filterwarnings("ignore", category=FutureWarning, module="TTS")
warnings.filterwarnings("ignore", message=".*weights_only.*", category=FutureWarning)
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tts_engine")

BASE_DIR   = Path(__file__).parent.parent
AUDIOS_DIR = BASE_DIR / "audios"


def _ensure_audios_dir() -> Path:
    """Crea la carpeta audios/ si no existe."""
    AUDIOS_DIR.mkdir(exist_ok=True)
    return AUDIOS_DIR


def _audio_filename(session_id: Optional[int] = None) -> Path:
    """Genera un nombre de fichero unico para el audio guardado."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sid = ("_s" + str(session_id)) if session_id else ""
    return _ensure_audios_dir() / f"audio_{ts}{sid}.wav"


# El modelo se carga una sola vez y se cachea
_tts_model = None


class _SuppressStdout:
    """Context manager que silencia stdout durante la sintesis de TTS."""
    def __enter__(self):
        import sys, os
        self._original = sys.stdout
        sys.stdout = open(os.devnull, "w")
        return self
    def __exit__(self, *args):
        import sys
        sys.stdout.close()
        sys.stdout = self._original


def is_available() -> bool:
    """Comprueba si Coqui TTS esta instalado."""
    try:
        from TTS.api import TTS  # noqa
        return True
    except ImportError:
        return False


def is_enabled() -> bool:
    """Devuelve True si TTS esta activado via variable de entorno."""
    return os.environ.get("TTS_ENABLED", "false").lower() == "true"


def set_enabled(value: bool):
    """Activa o desactiva TTS en tiempo de ejecucion."""
    os.environ["TTS_ENABLED"] = "true" if value else "false"


def get_voice_sample() -> Optional[str]:
    """Devuelve la ruta al fichero WAV de muestra configurado."""
    path = os.environ.get("TTS_VOICE_SAMPLE", "").strip()
    return path if path else None


def _get_model():
    """Carga el modelo XTTS-v2 la primera vez y lo cachea en memoria."""
    global _tts_model
    if _tts_model is None:
        if not is_available():
            raise RuntimeError(
                "Coqui TTS no esta instalado. Ejecuta: pip install TTS"
            )
        from TTS.api import TTS
        import torch

        os.environ["COQUI_TOS_AGREED"] = "1"
        device = os.environ.get("TTS_DEVICE", "cpu")

        # En Mac con MPS usar cpu (XTTS-v2 no es compatible con MPS)
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info("Cargando modelo XTTS-v2 en %s...", device)
        _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        logger.info("Modelo XTTS-v2 cargado.")
    return _tts_model


def _clean_text(text: str) -> str:
    """Limpia el texto antes de sintetizarlo."""
    import re
    # Eliminar markdown
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"_+", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # links
    # Eliminar URLs
    text = re.sub(r"https?://\S+", "", text)
    # Colapsar espacios y saltos
    text = re.sub(r"\s+", " ", text).strip()
    # XTTS-v2 tiene limite de ~250 palabras por llamada
    words = text.split()
    if len(words) > 200:
        text = " ".join(words[:200]) + "."
    return text


def synthesize(text: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Sintetiza texto a audio WAV usando la voz clonada.

    text        : texto a sintetizar
    output_path : ruta de salida (si None, crea un fichero temporal)

    Devuelve la ruta al fichero WAV generado, o None si falla.
    """
    sample = get_voice_sample()
    if not sample:
        logger.error("TTS_VOICE_SAMPLE no configurado en start.sh")
        return None

    if not Path(sample).exists():
        logger.error("Fichero de muestra de voz no encontrado: %s", sample)
        return None

    text = _clean_text(text)
    if not text:
        return None

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        output_path = tmp.name
        tmp.close()

    try:
        model = _get_model()
        language = os.environ.get("TTS_LANGUAGE", "es")
        with _SuppressStdout():
            model.tts_to_file(
                text=text,
                speaker_wav=sample,
                language=language,
                file_path=output_path,
            )
        return output_path
    except Exception as e:
        logger.error("Error sintetizando audio: %s", e)
        Path(output_path).unlink(missing_ok=True)
        return None


def synthesize_chunks(text: str, session_id: Optional[int] = None) -> Optional[str]:
    """
    Sintetiza textos largos dividiendo en frases y concatenando el audio.
    Guarda una copia permanente en audios/ y devuelve la ruta al WAV temporal.
    """
    import re

    # Dividir por frases
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for s in sentences:
        if len((current + " " + s).split()) > 180:
            if current:
                chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip()
    if current:
        chunks.append(current)

    if not chunks:
        return None

    if len(chunks) == 1:
        tmp_path = synthesize(chunks[0])
        if tmp_path:
            _save_audio_copy(tmp_path, session_id)
        return tmp_path

    # Sintetizar cada chunk y concatenar
    try:
        import wave
        tmp_files = []
        for chunk in chunks:
            path = synthesize(chunk)
            if path:
                tmp_files.append(path)

        if not tmp_files:
            return None

        # Concatenar WAVs
        out_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        out_path = out_tmp.name
        out_tmp.close()

        with wave.open(out_path, "wb") as out_wav:
            for i, fpath in enumerate(tmp_files):
                with wave.open(fpath, "rb") as w:
                    if i == 0:
                        out_wav.setparams(w.getparams())
                    out_wav.writeframes(w.readframes(w.getnframes()))

        for f in tmp_files:
            Path(f).unlink(missing_ok=True)

        _save_audio_copy(out_path, session_id)
        return out_path

    except Exception as e:
        logger.error("Error concatenando audio: %s", e)
        return None


def _save_audio_copy(tmp_path: str, session_id: Optional[int] = None):
    """Guarda una copia permanente del audio en audios/."""
    import shutil
    try:
        dest = _audio_filename(session_id)
        shutil.copy2(tmp_path, dest)
        logger.debug("Audio guardado en %s", dest)
    except Exception as e:
        logger.warning("No se pudo guardar copia del audio: %s", e)
