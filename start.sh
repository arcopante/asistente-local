#!/usr/bin/env bash
# ============================================================
#  start.sh — Script de arranque del Agente LM Studio
#  Edita las variables de esta sección antes de ejecutar.
# ============================================================

# ── Telegram ─────────────────────────────────────────────────
export TELEGRAM_TOKEN="TU_TOKEN_AQUI"          # Token del bot de BotFather
export TELEGRAM_ALLOWED_USERS=""               # IDs separados por coma (vacío = todos)
                                               # Ejemplo: "123456789,987654321"
export TELEGRAM_MAX_FILE_MB="20"               # Tamaño máximo de fichero en MB

# ── Backend LLM ──────────────────────────────────────────────
export BACKEND="lmstudio"                      # lmstudio | ollama

# ── LM Studio ────────────────────────────────────────────────
export LMSTUDIO_HOST="http://localhost:1234"   # URL del servidor LM Studio

# ── Ollama ───────────────────────────────────────────────────
export OLLAMA_HOST="http://localhost:11434"    # URL del servidor Ollama

# ── OpenRouter ───────────────────────────────────────────────
export OPENROUTER_API_KEY=""                   # sk-or-... (obtener en openrouter.ai/keys)
export OPENROUTER_MODEL=""                     # Ej: mistralai/mistral-7b-instruct

export LMSTUDIO_DEFAULT_MODEL=""               # Modelo por defecto (vacío = autodetectar)
export LMSTUDIO_MAX_TOKENS="2048"              # Tokens máximos por respuesta
export LMSTUDIO_TEMPERATURE="0.7"              # Temperatura (0.0 = determinista, 1.0 = creativo)
export LMSTUDIO_CONTEXT_MESSAGES="30"          # Mensajes de historial enviados al LLM

# ── Whisper (transcripción de audio) ─────────────────────────
export WHISPER_MODEL="base"                    # tiny | base | small | medium | large-v3
export WHISPER_DEVICE="cpu"                    # cpu | cuda (si tienes GPU compatible)
export WHISPER_LANGUAGE=""                     # es, en, fr... (vacío = autodetectar)

# ── Agente ───────────────────────────────────────────────────
export AGENT_MODE="both"                       # terminal | telegram | both
export AGENT_LOG_LEVEL="WARNING"               # DEBUG | INFO | WARNING | ERROR

# ============================================================
#  NO EDITAR A PARTIR DE AQUÍ
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

# Verificar entorno virtual
if [ ! -d "$VENV" ]; then
    echo "❌ Entorno virtual no encontrado. Ejecuta primero: ./setup.sh"
    exit 1
fi

# Verificar token de Telegram si el modo lo requiere
if [ "$AGENT_MODE" = "telegram" ] || [ "$AGENT_MODE" = "both" ]; then
    if [ "$TELEGRAM_TOKEN" = "TU_TOKEN_AQUI" ] || [ -z "$TELEGRAM_TOKEN" ]; then
        echo "❌ TELEGRAM_TOKEN no configurado en start.sh"
        echo "   Edita start.sh y pon tu token de bot de Telegram."
        exit 1
    fi
fi

# Activar entorno virtual y lanzar agente
source "$VENV/bin/activate"
echo "🤖 Iniciando agente (modo: $AGENT_MODE)..."
cd "$SCRIPT_DIR"
exec python3 agent.py "$@"
