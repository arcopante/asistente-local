"""
llm_client.py — Cliente LLM generico compatible con LM Studio y Ollama.

Ambos exponen una API compatible con OpenAI en /v1, por lo que chat,
streaming y listado de modelos funcionan igual en los dos backends.

Las operaciones especificas de cada backend (cargar/descargar modelos)
se implementan por separado segun BACKEND.

Variables de entorno relevantes (configuradas en start.sh):
  BACKEND                  lmstudio | ollama  (por defecto: lmstudio)
  LMSTUDIO_HOST            http://localhost:1234
  OLLAMA_HOST              http://localhost:11434
"""

import json
import os
import httpx
from typing import Iterator, Optional, List, Tuple

# ── Configuracion ─────────────────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Elimina bloques de razonamiento interno (<think>...</think>) de la respuesta."""
    import re
    # Elimina bloques <think>...</think> incluyendo variantes con saltos de linea
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def _backend() -> str:
    return os.environ.get("BACKEND", "lmstudio").lower()

def _base_url() -> str:
    if _backend() == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        return host + "/v1"
    host = os.environ.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
    return host + "/v1"

def _client() -> httpx.Client:
    return httpx.Client(base_url=_base_url(), timeout=120.0)


# ── Modelos ───────────────────────────────────────────────────────────────────

def list_models() -> List[dict]:
    """Lista los modelos disponibles en el backend activo."""
    with _client() as c:
        r = c.get("/models")
        r.raise_for_status()
        return r.json().get("data", [])


def get_loaded_model() -> Optional[str]:
    """Devuelve el primer modelo disponible."""
    models = list_models()
    return models[0].get("id") if models else None


def load_model(model_id: str) -> bool:
    """
    Carga un modelo.
    - LM Studio: no tiene endpoint explicito, se provoca con una inferencia minima.
    - Ollama: pull del modelo si no esta descargado, luego lo activa automaticamente.
    """
    if _backend() == "ollama":
        return _ollama_pull(model_id)
    # LM Studio: forzar carga con inferencia minima
    with _client() as c:
        try:
            r = c.post("/chat/completions", json={
                "model": model_id,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            })
            r.raise_for_status()
            return True
        except Exception:
            return False


def unload_model(model_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Descarga un modelo de memoria.
    - LM Studio: usa el endpoint no documentado DELETE /api/v0/models/<id>.
    - Ollama: no soporta descarga de memoria via API (los modelos se descargan solos).
    Devuelve (ok, mensaje).
    """
    if _backend() == "ollama":
        return False, "Ollama gestiona la memoria automaticamente. No es necesario descargar modelos manualmente."

    if not model_id:
        model_id = get_loaded_model()
    if not model_id:
        return False, "No hay ningun modelo cargado actualmente."

    base = os.environ.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
    try:
        with httpx.Client(base_url=base, timeout=30.0) as c:
            r = c.delete("/api/v0/models/" + model_id)
            if r.status_code in (200, 204):
                return True, model_id
            r2 = c.post("/api/v0/models/unload", json={"identifier": model_id})
            if r2.status_code in (200, 204):
                return True, model_id
            return False, "LM Studio respondio " + str(r.status_code) + ". Puede que esta version no soporte descarga via API."
    except Exception as e:
        return False, str(e)


# ── Inferencia ────────────────────────────────────────────────────────────────

def chat_stream(
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> Iterator[str]:
    """Genera respuesta en streaming. Compatible con LM Studio y Ollama.
    Filtra bloques <think>...</think> de modelos con razonamiento visible."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    in_think = False   # True mientras estamos dentro de un bloque <think>
    buf = ""           # buffer para detectar etiquetas partidas entre chunks

    with httpx.Client(base_url=_base_url(), timeout=120.0) as c:
        with c.stream("POST", "/chat/completions", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content", "")
                        if not delta:
                            continue

                        buf += delta
                        out = ""

                        while buf:
                            if in_think:
                                end = buf.find("</think>")
                                if end != -1:
                                    buf = buf[end + 8:]  # saltar </think>
                                    in_think = False
                                else:
                                    buf = ""  # consumir todo, seguimos en think
                            else:
                                start = buf.find("<think>")
                                if start != -1:
                                    out += buf[:start]
                                    buf = buf[start + 7:]
                                    in_think = True
                                else:
                                    # Guardar posible inicio de etiqueta incompleta
                                    if buf.endswith("<"):
                                        out += buf[:-1]
                                        buf = "<"
                                        break
                                    else:
                                        out += buf
                                        buf = ""

                        if out:
                            yield out

                    except Exception:
                        continue


def chat(
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> Tuple[str, int]:
    """Genera respuesta completa. Devuelve (texto, tokens_usados)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    with _client() as c:
        r = c.post("/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        content = _strip_thinking(data["choices"][0]["message"]["content"])
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens


# ── Helpers especificos de Ollama ─────────────────────────────────────────────

def _ollama_pull(model_id: str) -> bool:
    """Descarga un modelo en Ollama si no esta disponible localmente."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with httpx.Client(base_url=host, timeout=300.0) as c:
            r = c.post("/api/pull", json={"name": model_id, "stream": False})
            return r.status_code == 200
    except Exception:
        return False


def backend_info() -> str:
    """Devuelve una cadena descriptiva del backend activo y su URL."""
    b = _backend()
    if b == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return "Ollama (" + host + ")"
    host = os.environ.get("LMSTUDIO_HOST", "http://localhost:1234")
    return "LM Studio (" + host + ")"
