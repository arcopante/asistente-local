# 🤖 Asistente Local v5.3

**Asistente conversacional que corre completamente en tu máquina.**  
Conectado a [LM Studio](https://lmstudio.ai), [Ollama](https://ollama.com) o [OpenRouter](https://openrouter.ai), controlable por terminal y por Telegram, con memoria persistente, tareas programadas y herramientas del sistema.

Sin suscripciones. Sin APIs de pago. Sin datos en la nube.

---

## ✨ Qué puede hacer

| Capacidad | Descripción |
|---|---|
| 💬 **Conversación** | Chat fluido con cualquier modelo local cargado en LM Studio u Ollama, o en la nube con OpenRouter |
| 🧠 **Memoria persistente** | Recuerda información entre sesiones via `MEMORY.md` |
| 🎭 **Personalidades (SOULs)** | Cambia de rol en cualquier momento: dev, ejecutivo, hacking ético, o el que crees |
| 📅 **Tareas programadas** | Cron integrado: notificación, LLM o shell. Horario fijo o aleatorio dentro de un rango |
| 🛠️ **Herramientas del sistema** | Ejecuta comandos, lee ficheros, abre apps, inspecciona el sistema |
| 🎙️ **Audio y voz (entrada)** | Transcripción automática de notas de voz y audios con Whisper local |
| 🔊 **Voz (salida)** | Responde con voz clonada (Coqui XTTS-v2) o con la voz del sistema (say/espeak) |
| 🖼️ **Generación de imágenes** | Si el modelo genera imágenes, las guarda en `downloads/` y las envía por Telegram |
| 📄 **Documentos** | Procesa PDFs, imágenes y ficheros de texto enviados por Telegram |
| 🔌 **Multi-backend** | Cambia entre LM Studio, Ollama y OpenRouter con `/motorllm` sin reiniciar |
| 🔒 **Seguridad** | Filtro de comandos peligrosos en dos niveles |
| 📱 **Telegram** | Bot completo con los mismos comandos que la terminal |

---

## 🚀 Instalación

### Requisitos

- Python 3.9+ (3.10 si usas voz clonada con Coqui)
- [LM Studio](https://lmstudio.ai), [Ollama](https://ollama.com) o cuenta en [OpenRouter](https://openrouter.ai)
- Token de bot de Telegram (opcional)

### 1 — Clonar y configurar

```bash
git clone https://github.com/arcopante/asistente-local.git
cd asistente-local
```

Edita `start.sh` con tus datos:

```bash
nano start.sh
```

Variables esenciales:

```bash
export TELEGRAM_TOKEN="TU_TOKEN_AQUI"
export TELEGRAM_ALLOWED_USERS="123456789"
export AGENT_MODE="both"
export BACKEND="lmstudio"   # lmstudio | ollama | openrouter
```

### 2 — Instalar dependencias

```bash
chmod +x setup.sh

./setup.sh          # instalación base
./setup.sh --voz    # base + clonación de voz (requiere Python 3.10)
```

### 3 — Activar el backend LLM

**LM Studio:**
1. Abre LM Studio → pestaña **Local Server** → **Start Server**
2. Carga el modelo que quieras usar

**Ollama:**
```bash
ollama serve
ollama pull llama3.2
```

**OpenRouter:**
```bash
export BACKEND="openrouter"
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="mistralai/mistral-7b-instruct"
```
Ver modelos disponibles en [openrouter.ai/models](https://openrouter.ai/models).

### 4 — Arrancar

```bash
chmod +x start.sh
./start.sh
```

---

## 📁 Estructura del proyecto

```
asistente-local/
├── start.sh              # ⚙️  Configuración y punto de entrada
├── setup.sh              # 📦 Instalador de dependencias
├── agent.py              # 🧠 Lógica principal
├── requirements.txt      # 📄 Dependencias Python
│
├── SOUL.md               # 🎭 Personalidad por defecto
├── MEMORY.md             # 🧠 Memoria persistente (no subir a git)
├── souls/                # 🎭 Personalidades adicionales
│   ├── trabajo.md
│   ├── dev.md
│   └── hacking.md
│
├── history.db            # 🗃️  Historial SQLite (no subir a git)
├── cron_jobs.json        # 📅 Tareas programadas (no subir a git)
├── downloads/            # 🖼️  Ficheros generados por el LLM
├── audios/               # 🔊 Historial de audios TTS (no subir a git)
│
└── core/
    ├── database.py       # 🗃️  Historial en SQLite
    ├── llm_client.py     # 🔌 Cliente LLM (LM Studio / Ollama / OpenRouter)
    ├── commands.py       # ⌨️  Comandos slash (terminal)
    ├── cron_manager.py   # ⏰ Gestor de tareas programadas
    ├── telegram_bot.py   # 📱 Bot de Telegram
    ├── tools.py          # 🛠️  Herramientas del sistema
    ├── transcriber.py    # 🎙️  Transcripción de audio (Whisper)
    ├── tts_engine.py     # 🔊 Síntesis de voz (clonada o sistema)
    └── downloads.py      # 🖼️  Gestión de ficheros generados por el LLM
```

---

## ⌨️ Comandos

Los mismos comandos funcionan en terminal y en Telegram.

### Modelo y backend

| Comando | Descripción |
|---|---|
| `/list` | Modelos disponibles en el backend activo |
| `/load <modelo>` | Carga un modelo |
| `/unload` | Descarga el modelo activo |
| `/motorllm [backend]` | Cambia el motor LLM en caliente (`lmstudio`, `ollama`, `openrouter`) |
| `/status` | Estado actual: backend, modelo, sesión, soul activo |
| `/reset` | Nueva sesión (mantiene memoria y soul) |

### Memoria y contexto

| Comando | Descripción |
|---|---|
| `/memory <texto>` | Guarda información en la memoria persistente |
| `/compact` | El asistente resume la conversación y la guarda en memoria |
| `/search <texto>` | Busca en todo el historial de conversaciones |

### Sesiones

| Comando | Descripción |
|---|---|
| `/sessions` | Lista las últimas sesiones |
| `/sessionsdel <id>` | Borra una sesión por ID |
| `/sessionsclear` | Borra todas las sesiones excepto la actual y renumera desde 1 |

### SOULs — personalidades

| Comando | Descripción |
|---|---|
| `/souls` | Lista las personalidades disponibles |
| `/soul <nombre>` | Cambia de personalidad |
| `/soul` | Vuelve a la personalidad por defecto |

Crea tus propias personalidades añadiendo ficheros `.md` en `souls/`. SOULs incluidos: `trabajo.md`, `dev.md`, `hacking.md`.

### Herramientas del sistema

| Comando | Descripción |
|---|---|
| `/run <cmd>` | Ejecuta un comando de shell |
| `/open <app>` | Abre una aplicación o fichero |
| `/read <ruta>` | Lee y muestra un fichero |
| `/ls [ruta]` | Lista un directorio |
| `/sysinfo` | Información del sistema |
| `/download <ruta>` | *(Telegram)* Envía un fichero al chat |

### Tareas programadas (cron)

El cron es interno al agente. Las tareas sobreviven a reinicios mientras exista `cron_jobs.json`.

**Tres tipos de tarea:**

```bash
/cron 09:00 Buenos días                        # 🔔 Texto fijo a hora exacta
/cron 08:00-10:00 Buenos días                  # 🔔 Texto fijo a hora aleatoria en el rango
/cron */1h llm: Dame un consejo aleatorio      # 🤖 El LLM genera el mensaje
/cron 23:00 shell: ~/scripts/backup.sh         # ⚙️  Ejecuta un script
```

**Formatos de horario:** `HH:MM` · `HH:MM-HH:MM` (aleatorio) · `*/Nm` · `*/Nh`

| Comando | Descripción |
|---|---|
| `/cronlist` | Lista las tareas activas |
| `/crondel <id>` | Elimina una tarea |
| `/cronclear` | Borra todas las tareas y el fichero `cron_jobs.json` |

### Voz

| Comando | Descripción |
|---|---|
| `/voz clonada` | Activa respuestas con voz clonada (Coqui XTTS-v2) |
| `/voz sistema` | Activa respuestas con voz del sistema (`say` en macOS / `espeak` en Linux) |
| `/voz off` | Desactiva la voz |
| `/voz` | Muestra el modo activo, voz y velocidad configuradas |

### General

| Comando | Descripción |
|---|---|
| `/help` / `/ayuda` | Ayuda completa |
| `/exit` | Cierra el asistente |

---

## 🔊 Síntesis de voz (TTS)

El asistente puede responder con voz de dos formas distintas:

### Modo clonada (Coqui XTTS-v2)

Clona tu propia voz a partir de un fichero WAV de muestra. 100% local, sin enviar datos a internet.

1. Graba 10-30 segundos de tu voz en WAV y ponlo en el directorio raíz del agente
2. Configura en `start.sh`:
```bash
export TTS_VOICE_SAMPLE="voz_origen.wav"
export TTS_LANGUAGE="es"
```
3. Instala las dependencias (requiere Python 3.10):
```bash
./setup.sh --voz
```
4. Activa con `/voz clonada`

### Modo sistema

Usa el motor TTS nativo del sistema operativo. No requiere instalación adicional.

- **macOS**: usa `say` con las voces instaladas en el sistema
- **Linux**: usa `espeak` o `espeak-ng`

Configura en `start.sh`:
```bash
export TTS_SYSTEM_VOICE="Paulina"   # macOS: Paulina, Monica, Jorge...
export TTS_SYSTEM_RATE="175"        # palabras por minuto
```

Activa con `/voz sistema`.

> Cada audio generado se guarda en `audios/` con nombre `audio_YYYYMMDD_HHMMSS_sN.wav`.

---

## 🎙️ Transcripción de audio (entrada)

En Telegram, el asistente transcribe automáticamente notas de voz y ficheros de audio con [faster-whisper](https://github.com/SYSTRAN/faster-whisper), completamente local.

| Modelo | Tamaño | Velocidad | Precisión |
|---|---|---|---|
| `tiny` | ~75 MB | ⚡⚡⚡ | ★★☆☆ |
| `base` | ~145 MB | ⚡⚡ | ★★★☆ |
| `small` | ~466 MB | ⚡ | ★★★★ |
| `medium` | ~1.5 GB | 🐢 | ★★★★★ |

---

## 🖼️ Generación de imágenes y documentos

Si el modelo genera imágenes (modelos multimodales), el asistente las detecta automáticamente, las guarda en `downloads/` y las envía al chat de Telegram.

---

## 🔒 Seguridad en comandos de shell

**Bloqueados siempre:** `rm`, `sudo`, `shutdown`, `reboot`, `mkfs`, `dd`, `killall`, escritura en `/etc/`, `/boot/`, `/System/`...

**Requieren confirmación** (solo terminal, bloqueados en Telegram): `kill`, `pip install`, `brew install`, `apt install`, `systemctl`, `crontab`...

---

## ⚙️ Configuración (start.sh)

| Variable | Por defecto | Descripción |
|---|---|---|
| `BACKEND` | `lmstudio` | Motor LLM: `lmstudio`, `ollama` o `openrouter` |
| `TELEGRAM_TOKEN` | — | Token del bot (de @BotFather) |
| `TELEGRAM_ALLOWED_USERS` | vacío (todos) | IDs de usuario separados por coma |
| `TELEGRAM_MAX_FILE_MB` | `20` | Tamaño máximo de fichero |
| `LMSTUDIO_HOST` | `http://localhost:1234` | URL del servidor LM Studio |
| `OLLAMA_HOST` | `http://localhost:11434` | URL del servidor Ollama |
| `OPENROUTER_API_KEY` | — | API key de OpenRouter |
| `OPENROUTER_MODEL` | — | Modelo de OpenRouter, ej: `mistralai/mistral-7b-instruct` |
| `LMSTUDIO_DEFAULT_MODEL` | vacío | Modelo al arrancar |
| `LMSTUDIO_MAX_TOKENS` | `2048` | Tokens máximos por respuesta |
| `LMSTUDIO_TEMPERATURE` | `0.7` | Temperatura del modelo |
| `LMSTUDIO_CONTEXT_MESSAGES` | `30` | Mensajes de historial enviados al LLM |
| `AGENT_MODE` | `terminal` | `terminal` · `telegram` · `both` |
| `AGENT_LOG_LEVEL` | `WARNING` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `WHISPER_MODEL` | `base` | Modelo Whisper: `tiny`, `base`, `small`, `medium` |
| `WHISPER_DEVICE` | `cpu` | `cpu` o `cuda` |
| `WHISPER_LANGUAGE` | vacío (auto) | Código de idioma: `es`, `en`, `fr`... |
| `TTS_ENABLED` | `false` | Modo voz: `false`, `clonada` o `sistema` |
| `TTS_VOICE_SAMPLE` | — | Ruta al WAV de muestra (modo clonada) |
| `TTS_LANGUAGE` | `es` | Idioma de síntesis (modo clonada) |
| `TTS_DEVICE` | `cpu` | `cpu` o `cuda` (modo clonada) |
| `TTS_SYSTEM_VOICE` | — | Voz del sistema, ej: `Paulina` en macOS |
| `TTS_SYSTEM_RATE` | `175` | Velocidad en palabras por minuto |

---

## 🛠️ Dependencias

| Paquete | Uso |
|---|---|
| `httpx` | Comunicación con LM Studio / Ollama / OpenRouter |
| `rich` | Terminal con colores y tablas |
| `python-telegram-bot` | Bot de Telegram |
| `pypdf` | Extracción de texto de PDFs |
| `faster-whisper` | Transcripción de audio local |
| `TTS` *(opcional)* | Clonación de voz con Coqui XTTS-v2 |
| `torch` / `torchaudio` *(opcional)* | Motor de inferencia para TTS |

---

## 📝 Licencia

GPL-3.0 — puedes usar, modificar y distribuir este software, pero cualquier obra derivada debe publicarse bajo la misma licencia. Ver [LICENSE](LICENSE) para más detalles.
