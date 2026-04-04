"""
tts_engine.py — Sintesis de voz local con dos modos:

  clonada  — Coqui XTTS-v2, clona la voz de un fichero WAV de muestra
  sistema  — say (macOS) o espeak/festival (Linux), voz del sistema

Variables de entorno (configuradas en start.sh):
  TTS_ENABLED        false | clonada | sistema  (por defecto: false)
  TTS_VOICE_SAMPLE   ruta al WAV de muestra (solo modo clonada)
  TTS_LANGUAGE       es | en | fr | ...  (por defecto: es)
  TTS_DEVICE         cpu | cuda  (por defecto: cpu)
  TTS_SYSTEM_VOICE   voz del sistema, ej: "Paulina" en macOS (por defecto: segun OS)
  TTS_SYSTEM_RATE    velocidad en palabras por minuto, ej: 175  (por defecto: 175)
"""

import os
import platform
import subprocess
import tempfile
import logging
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="TTS")
warnings.filterwarnings("ignore", message=".*weights_only.*", category=FutureWarning)

from pathlib import Path
from typing import Optional

logger = logging.getLogger("tts_engine")

BASE_DIR   = Path(__file__).parent.parent
AUDIOS_DIR = BASE_DIR / "audios"

_tts_model = None  # modelo Coqui cacheado


# ── Directorio de audios ──────────────────────────────────────────────────────

def _ensure_audios_dir() -> Path:
    AUDIOS_DIR.mkdir(exist_ok=True)
    return AUDIOS_DIR


def _audio_filename(session_id: Optional[int] = None) -> Path:
    from datetime import datetime
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    sid = ("_s" + str(session_id)) if session_id else ""
    return _ensure_audios_dir() / f"audio_{ts}{sid}.wav"


# ── Estado ────────────────────────────────────────────────────────────────────

def get_mode() -> str:
    """Devuelve el modo TTS activo: 'false' | 'clonada' | 'sistema'."""
    return os.environ.get("TTS_ENABLED", "false").lower()


def is_enabled() -> bool:
    return get_mode() != "false"


def is_cloned() -> bool:
    return get_mode() == "clonada"


def is_sistema() -> bool:
    return get_mode() == "sistema"


def set_mode(mode: str):
    """Establece el modo TTS: 'false' | 'clonada' | 'sistema'."""
    os.environ["TTS_ENABLED"] = mode


# Alias para compatibilidad con codigo existente
def set_enabled(value: bool):
    set_mode("clonada" if value else "false")


def get_voice_sample() -> Optional[str]:
    path = os.environ.get("TTS_VOICE_SAMPLE", "").strip()
    return path if path else None


def get_system_voice() -> str:
    return os.environ.get("TTS_SYSTEM_VOICE", "").strip()


def get_system_rate() -> int:
    try:
        return int(os.environ.get("TTS_SYSTEM_RATE", "175"))
    except ValueError:
        return 175


# ── Comprobaciones ────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Comprueba si Coqui TTS esta instalado (modo clonada)."""
    try:
        from TTS.api import TTS  # noqa
        return True
    except ImportError:
        return False


def is_sistema_available() -> bool:
    """Comprueba si hay un motor TTS del sistema disponible."""
    system = platform.system()
    if system == "Darwin":
        return True  # say siempre disponible en macOS
    # Linux: espeak o festival
    for cmd in ("espeak", "espeak-ng", "festival"):
        result = subprocess.run(["which", cmd], capture_output=True)
        if result.returncode == 0:
            return True
    return False


# ── Limpieza de texto ─────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    import re
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"_+", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Modo clonada (Coqui XTTS-v2) ─────────────────────────────────────────────

class _SuppressStdout:
    def __enter__(self):
        import sys
        self._original = sys.stdout
        sys.stdout = open(os.devnull, "w")
        return self
    def __exit__(self, *args):
        import sys
        sys.stdout.close()
        sys.stdout = self._original


def _get_model():
    global _tts_model
    if _tts_model is None:
        if not is_available():
            raise RuntimeError("Coqui TTS no instalado. Ejecuta: pip install TTS")
        from TTS.api import TTS
        os.environ["COQUI_TOS_AGREED"] = "1"
        device = os.environ.get("TTS_DEVICE", "cpu")
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Cargando modelo XTTS-v2 en %s...", device)
        _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    return _tts_model


def synthesize(text: str, output_path: Optional[str] = None) -> Optional[str]:
    """Sintetiza con voz clonada (Coqui). Devuelve ruta WAV o None."""
    sample = get_voice_sample()
    if not sample or not Path(sample).exists():
        logger.error("TTS_VOICE_SAMPLE no configurado o no encontrado.")
        return None
    text = _clean_text(text)
    if not text:
        return None
    words = text.split()
    if len(words) > 200:
        text = " ".join(words[:200]) + "."
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        output_path = tmp.name
        tmp.close()
    try:
        model    = _get_model()
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
        logger.error("Error sintetizando audio clonado: %s", e)
        Path(output_path).unlink(missing_ok=True)
        return None


# ── Modo sistema (say / espeak) ───────────────────────────────────────────────

def synthesize_sistema(text: str, output_path: Optional[str] = None) -> Optional[str]:
    """Sintetiza con TTS del sistema. Devuelve ruta WAV o None."""
    text = _clean_text(text)
    if not text:
        return None
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        output_path = tmp.name
        tmp.close()

    system = platform.system()
    voice  = get_system_voice()
    rate   = get_system_rate()

    try:
        if system == "Darwin":
            # say -v Paulina -r 175 -o salida.aiff texto
            # say genera AIFF, convertimos a WAV con afconvert
            aiff_path = output_path.replace(".wav", ".aiff")
            cmd = ["say", "-r", str(rate), "-o", aiff_path]
            if voice:
                cmd += ["-v", voice]
            cmd.append(text)
            subprocess.run(cmd, check=True, capture_output=True)
            # Convertir AIFF a WAV
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16", aiff_path, output_path],
                check=True, capture_output=True
            )
            Path(aiff_path).unlink(missing_ok=True)

        elif system == "Linux":
            # espeak-ng o espeak
            espeak = "espeak-ng" if subprocess.run(
                ["which", "espeak-ng"], capture_output=True
            ).returncode == 0 else "espeak"
            lang = os.environ.get("TTS_LANGUAGE", "es")
            cmd = [espeak, "-v", voice or lang, "-s", str(rate), "-w", output_path, text]
            subprocess.run(cmd, check=True, capture_output=True)

        else:
            logger.error("TTS sistema no soportado en %s", system)
            return None

        return output_path

    except Exception as e:
        logger.error("Error TTS sistema: %s", e)
        Path(output_path).unlink(missing_ok=True)
        return None


# ── Punto de entrada principal ────────────────────────────────────────────────

def synthesize_chunks(text: str, session_id: Optional[int] = None) -> Optional[str]:
    """
    Sintetiza texto largo dividiendolo en frases.
    Usa el modo activo (clonada o sistema).
    Guarda copia en audios/ y devuelve ruta al WAV temporal.
    """
    import re

    mode = get_mode()
    if mode == "sistema":
        # El TTS del sistema maneja textos largos sin problemas
        path = synthesize_sistema(text)
        if path:
            _save_audio_copy(path, session_id)
        return path

    # Modo clonada: dividir en chunks
    text = _clean_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
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
        path = synthesize(chunks[0])
        if path:
            _save_audio_copy(path, session_id)
        return path

    try:
        import wave
        tmp_files = [p for p in (synthesize(c) for c in chunks) if p]
        if not tmp_files:
            return None

        out_tmp  = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
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
    import shutil
    try:
        dest = _audio_filename(session_id)
        shutil.copy2(tmp_path, dest)
    except Exception as e:
        logger.warning("No se pudo guardar copia del audio: %s", e)
