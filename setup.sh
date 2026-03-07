#!/usr/bin/env bash
# setup.sh — Instalación del agente conversacional LM Studio + Telegram
set -e

echo "🤖 Instalando Agente LM Studio..."

OS=$(uname -s)
echo "→ Sistema detectado: $OS"

PYTHON=$(which python3 || which python)
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "→ Python encontrado: $PY_VERSION"

if [ ! -d ".venv" ]; then
    echo "→ Creando entorno virtual..."
    $PYTHON -m venv .venv
fi

source .venv/bin/activate

echo "→ Instalando dependencias..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ "$OS" = "Linux" ]; then
    if ! command -v notify-send &> /dev/null; then
        echo "→ Instalando libnotify-bin..."
        sudo apt-get install -y libnotify-bin 2>/dev/null || true
    fi
fi

mkdir -p logs

echo ""
echo "✅ Instalación completa."
echo ""
echo "Pasos siguientes:"
echo "  1. Edita start.sh y pon tu TELEGRAM_TOKEN"
echo "  2. Configura AGENT_MODE (terminal | telegram | both)"
echo "  3. Ejecuta: ./start.sh"
