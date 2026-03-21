#!/usr/bin/env bash
# ============================================================
#  setup.sh — Instalación del Asistente Local
#
#  Uso:
#    ./setup.sh          Instalación base
#    ./setup.sh --voz    Instalación base + clonación de voz (TTS)
# ============================================================
set -e

INSTALL_VOZ=false
if [ "$1" = "--voz" ]; then
    INSTALL_VOZ=true
fi

echo "🤖 Instalando Asistente Local..."
OS=$(uname -s)
echo "→ Sistema detectado: $OS"

# ── Entorno virtual ───────────────────────────────────────────
if [ "$INSTALL_VOZ" = true ]; then
    echo ""
    echo "🔊 Modo instalación con clonación de voz (TTS)"
    echo "   Requiere Python 3.10.x — comprobando..."

    # Buscar Python 3.10 via pyenv o sistema
    if command -v pyenv &> /dev/null; then
        PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
        PY310="$PYENV_ROOT/versions/3.10.13/bin/python"
        if [ ! -f "$PY310" ]; then
            echo "→ Instalando Python 3.10.13 con pyenv..."
            pyenv install 3.10.13
        fi
        PYTHON="$PY310"
    else
        # Intentar python3.10 del sistema
        if command -v python3.10 &> /dev/null; then
            PYTHON=$(which python3.10)
        else
            echo "❌ Python 3.10 no encontrado."
            echo "   Instala pyenv y ejecuta: pyenv install 3.10.13"
            echo "   O instala Python 3.10 desde tu gestor de paquetes."
            exit 1
        fi
    fi
else
    PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null)
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "→ Python: $PY_VERSION ($PYTHON)"

# Crear o reutilizar entorno virtual
if [ ! -d ".venv" ]; then
    echo "→ Creando entorno virtual..."
    $PYTHON -m venv .venv
else
    echo "→ Usando entorno virtual existente (.venv)"
fi

source .venv/bin/activate
echo "→ Actualizando pip..."
pip install -q --upgrade pip

# ── Dependencias base ─────────────────────────────────────────
echo "→ Instalando dependencias base..."
pip install -q \
    "httpx>=0.27.0" \
    "rich>=13.7.0" \
    "python-telegram-bot[http2]>=21.0" \
    "pypdf>=4.0.0" \
    "faster-whisper>=1.0.0"

# ── Dependencias TTS (opcionales) ─────────────────────────────
if [ "$INSTALL_VOZ" = true ]; then
    echo ""
    echo "→ Instalando dependencias de clonación de voz..."
    echo "  (puede tardar varios minutos, descarga ~2GB)"

    pip install -q torch==2.4.0 torchaudio==2.4.0
    pip install -q TTS
    pip install -q sounddevice soundfile numpy
    pip install -q transformers==4.37.2 tokenizers==0.15.2
    pip install -q openai-whisper openai

    echo "✅ Dependencias TTS instaladas."
    echo ""
    echo "Pasos para usar la clonación de voz:"
    echo "  1. Graba tu voz en un WAV de 10-30 segundos"
    echo "  2. En start.sh configura TTS_VOICE_SAMPLE con la ruta al WAV"
    echo "  3. Arranca el agente y usa /voz on en Telegram"
fi

# ── Extras del sistema ────────────────────────────────────────
if [ "$OS" = "Linux" ]; then
    if ! command -v notify-send &> /dev/null; then
        echo "→ Instalando libnotify-bin para notificaciones..."
        sudo apt-get install -y libnotify-bin 2>/dev/null || true
    fi
fi

mkdir -p logs downloads

echo ""
echo "✅ Instalación completa."
echo ""
echo "Pasos siguientes:"
echo "  1. Edita start.sh con tu TELEGRAM_TOKEN y configura el backend"
echo "  2. Elige el modo: AGENT_MODE=terminal | telegram | both"
echo "  3. Ejecuta: ./start.sh"
if [ "$INSTALL_VOZ" = false ]; then
    echo ""
    echo "Para instalar la clonación de voz más adelante:"
    echo "  ./setup.sh --voz"
fi
