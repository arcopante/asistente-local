"""
downloads.py — Gestiona la carpeta de descargas del agente.

Guarda ficheros generados por el LLM (imágenes, documentos) en
una carpeta 'downloads/' dentro del directorio del agente.
"""

import os
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

BASE_DIR = Path(__file__).parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"


def ensure_dir() -> Path:
    """Crea la carpeta downloads/ si no existe."""
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    return DOWNLOADS_DIR


def _unique_filename(ext: str, prefix: str = "file") -> Path:
    """Genera un nombre de fichero unico con timestamp."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ensure_dir() / f"{prefix}_{ts}{ext}"


def save_base64(data: str, mime_type: str = "image/png") -> Optional[Path]:
    """
    Guarda un fichero codificado en base64.
    Devuelve la ruta del fichero guardado, o None si falla.
    """
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/html": ".html",
    }
    ext = ext_map.get(mime_type, ".bin")
    prefix = "img" if mime_type.startswith("image/") else "doc"
    try:
        raw = base64.b64decode(data)
        path = _unique_filename(ext, prefix)
        path.write_bytes(raw)
        return path
    except Exception:
        return None


def save_bytes(data: bytes, filename: str) -> Optional[Path]:
    """Guarda bytes directamente con el nombre indicado (añade timestamp si ya existe)."""
    ensure_dir()
    target = DOWNLOADS_DIR / filename
    if target.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = DOWNLOADS_DIR / f"{stem}_{ts}{suffix}"
    try:
        target.write_bytes(data)
        return target
    except Exception:
        return None


def extract_generated_files(response_data: dict) -> list:
    """
    Analiza la respuesta raw de la API y extrae ficheros generados.
    Soporta:
      - Bloques de contenido con type='image_url' y data URI base64
      - Campo 'images' en la respuesta (algunos backends)
      - Markdown con data URIs embebidos en el texto

    Devuelve lista de dicts: [{"path": Path, "mime": str, "label": str}]
    """
    files = []

    choices = response_data.get("choices", [])
    for choice in choices:
        msg = choice.get("message", {})

        # Caso 1: content es una lista de bloques (multimodal)
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    path = _save_data_uri(url)
                    if path:
                        files.append({"path": path, "mime": _mime_from_uri(url), "label": "Imagen generada"})

        # Caso 2: content es texto con data URIs embebidos
        elif isinstance(content, str):
            import re
            for match in re.finditer(r'data:(image/[^;]+|application/pdf);base64,([A-Za-z0-9+/=]+)', content):
                mime = match.group(1)
                b64 = match.group(2)
                path = save_base64(b64, mime)
                if path:
                    files.append({"path": path, "mime": mime, "label": "Imagen generada"})

    # Caso 3: campo 'images' directo en la respuesta (Ollama imagen experimental)
    for img in response_data.get("images", []):
        if isinstance(img, str):
            path = save_base64(img, "image/png")
            if path:
                files.append({"path": path, "mime": "image/png", "label": "Imagen generada"})

    return files


def _save_data_uri(uri: str) -> Optional[Path]:
    """Extrae y guarda el contenido de un data URI base64."""
    if not uri.startswith("data:"):
        return None
    try:
        header, data = uri.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        return save_base64(data, mime)
    except Exception:
        return None


def _mime_from_uri(uri: str) -> str:
    try:
        return uri.split(":")[1].split(";")[0]
    except Exception:
        return "application/octet-stream"
