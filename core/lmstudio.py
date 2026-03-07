"""
lmstudio.py — Cliente para LM Studio (compatible con OpenAI API)
"""

import httpx
from typing import Iterator, Optional, List


LMSTUDIO_BASE = "http://localhost:1234/v1"


def _client() -> httpx.Client:
    return httpx.Client(base_url=LMSTUDIO_BASE, timeout=120.0)


def list_models() -> List[dict]:
    """Lista los modelos disponibles en LM Studio."""
    with _client() as c:
        r = c.get("/models")
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])


def get_loaded_model() -> Optional[str]:
    """Devuelve el modelo actualmente cargado (primero de la lista)."""
    models = list_models()
    if models:
        return models[0].get("id")
    return None


def load_model(model_id: str) -> bool:
    """
    LM Studio no tiene endpoint explícito de carga;
    se provoca cargando con una inferencia mínima.
    """
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


def unload_model(model_id=None):
    """
    Descarga un modelo de memoria usando el endpoint no documentado de LM Studio.
    Si no se indica model_id, descarga el modelo actualmente cargado.
    Devuelve (ok: bool, mensaje: str).
    """
    if not model_id:
        model_id = get_loaded_model()
    if not model_id:
        return False, "No hay ningun modelo cargado actualmente."

    # LM Studio expone /api/v0/models/<id>/unload (desde v0.3.x)
    base = LMSTUDIO_BASE.replace("/v1", "")
    try:
        with httpx.Client(base_url=base, timeout=30.0) as c:
            # Intento 1: DELETE /api/v0/models/<id>
            r = c.delete("/api/v0/models/" + model_id)
            if r.status_code in (200, 204):
                return True, model_id
            # Intento 2: POST /api/v0/models/unload (builds anteriores)
            r2 = c.post("/api/v0/models/unload", json={"identifier": model_id})
            if r2.status_code in (200, 204):
                return True, model_id
            return False, "LM Studio respondio " + str(r.status_code) + ". Puede que esta version no soporte descarga via API."
    except Exception as e:
        return False, str(e)


def chat_stream(
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> Iterator[str]:
    """Genera respuesta en streaming desde LM Studio."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    with httpx.Client(base_url=LMSTUDIO_BASE, timeout=120.0) as c:
        with c.stream("POST", "/chat/completions", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    import json
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue


def chat(
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> tuple[str, int]:
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
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens
