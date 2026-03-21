"""
llm_client.py — Cliente LLM generico compatible con LM Studio, Ollama y OpenRouter.

Los tres exponen una API compatible con OpenAI en /v1.

Variables de entorno relevantes (configuradas en start.sh):
  BACKEND                  lmstudio | ollama | openrouter  (por defecto: lmstudio)
  LMSTUDIO_HOST            http://localhost:1234
  OLLAMA_HOST              http://localhost:11434
  OPENROUTER_API_KEY       sk-or-...
  OPENROUTER_MODEL         mistralai/mistral-7b-instruct  (obligatorio con openrouter)
"""

import json
import os
import httpx
from typing import Iterator, Optional, List, Tuple


# ── Helpers internos ──────────────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Elimina bloques de razonamiento interno (<think>...</think>) de la respuesta."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def _backend() -> str:
    return os.environ.get("BACKEND", "lmstudio").lower()


def _base_url() -> str:
    b = _backend()
    if b == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        return host + "/v1"
    if b == "openrouter":
        return "https://openrouter.ai/api/v1"
    host = os.environ.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
    return host + "/v1"


def _headers() -> dict:
    """Cabeceras HTTP. OpenRouter requiere Authorization y cabeceras opcionales."""
    b = _backend()
    if b == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY no configurado en start.sh")
        return {
            "Authorization": "Bearer " + key,
            "HTTP-Referer": "https://github.com/arcopante/asistente-local",
            "X-Title": "Asistente Local",
        }
    return {}


def _client() -> httpx.Client:
    return httpx.Client(base_url=_base_url(), headers=_headers(), timeout=120.0)


def _resolve_model(model: Optional[str]) -> str:
    """
    Resuelve el modelo a usar.
    En OpenRouter el modelo es obligatorio y se puede fijar en start.sh.
    En LM Studio y Ollama se usa el que venga del estado del agente.
    """
    if _backend() == "openrouter":
        return (
            model
            or os.environ.get("OPENROUTER_MODEL", "")
            or "mistralai/mistral-7b-instruct"
        )
    return model or ""


# ── Modelos ───────────────────────────────────────────────────────────────────

def list_models() -> List[dict]:
    """Lista los modelos disponibles en el backend activo."""
    with _client() as c:
        r = c.get("/models")
        r.raise_for_status()
        return r.json().get("data", [])


def get_loaded_model() -> Optional[str]:
    """Devuelve el modelo activo. En OpenRouter devuelve el configurado en start.sh."""
    if _backend() == "openrouter":
        return os.environ.get("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")
    models = list_models()
    return models[0].get("id") if models else None


def load_model(model_id: str) -> bool:
    """
    Carga un modelo.
    - LM Studio: inferencia minima para forzar la carga.
    - Ollama: pull automatico si no esta descargado.
    - OpenRouter: no aplica, el modelo se selecciona por parametro.
    """
    if _backend() == "openrouter":
        # En OpenRouter no hay carga local; simplemente actualizamos la variable
        os.environ["OPENROUTER_MODEL"] = model_id
        return True
    if _backend() == "ollama":
        return _ollama_pull(model_id)
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
    - LM Studio: endpoint DELETE /api/v0/models/<id>.
    - Ollama / OpenRouter: no aplica.
    """
    b = _backend()
    if b == "ollama":
        return False, "Ollama gestiona la memoria automaticamente."
    if b == "openrouter":
        return False, "OpenRouter es un servicio en la nube, no hay modelo local que descargar."

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
            return False, "LM Studio respondio " + str(r.status_code)
    except Exception as e:
        return False, str(e)


# ── Inferencia ────────────────────────────────────────────────────────────────

def chat_stream(
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> Iterator[str]:
    """Genera respuesta en streaming. Filtra bloques <think>...</think>."""
    payload = {
        "model": _resolve_model(model),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    in_think = False
    buf = ""

    with httpx.Client(base_url=_base_url(), headers=_headers(), timeout=120.0) as c:
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
                                    buf = buf[end + 8:]
                                    in_think = False
                                else:
                                    buf = ""
                            else:
                                start = buf.find("<think>")
                                if start != -1:
                                    out += buf[:start]
                                    buf = buf[start + 7:]
                                    in_think = True
                                else:
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
) -> Tuple[str, int, list]:
    """
    Genera respuesta completa.
    Devuelve (texto, tokens_usados, ficheros_generados).
    """
    payload = {
        "model": _resolve_model(model),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    with _client() as c:
        r = c.post("/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()

        raw_content = data["choices"][0]["message"].get("content") or ""
        if isinstance(raw_content, list):
            text = " ".join(b.get("text", "") for b in raw_content if b.get("type") == "text")
        else:
            text = raw_content
        text = _strip_thinking(text)

        tokens = data.get("usage", {}).get("total_tokens", 0)

        from core.downloads import extract_generated_files
        files = extract_generated_files(data)

        return text, tokens, files


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


# ── Info del backend ──────────────────────────────────────────────────────────

def backend_info() -> str:
    """Devuelve una cadena descriptiva del backend activo."""
    b = _backend()
    if b == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return "Ollama (" + host + ")"
    if b == "openrouter":
        model = os.environ.get("OPENROUTER_MODEL", "no configurado")
        return "OpenRouter (modelo: " + model + ")"
    host = os.environ.get("LMSTUDIO_HOST", "http://localhost:1234")
    return "LM Studio (" + host + ")"
