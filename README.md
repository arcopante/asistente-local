# 🤖 Asistente Local v5.2

**Asistente conversacional que corre completamente en tu máquina.**  
Conectado a [LM Studio](https://lmstudio.ai) u [Ollama](https://ollama.com), controlable por terminal y por Telegram, con memoria persistente, tareas programadas y herramientas del sistema.

Sin suscripciones. Sin APIs de pago. Sin datos en la nube.

> Compatible con **LM Studio**, **Ollama** y **OpenRouter**.

---

## ✨ Qué puede hacer

| Capacidad | Descripción |
|---|---|
| 💬 **Conversación** | Chat fluido con cualquier modelo local cargado en LM Studio |
| 🧠 **Memoria persistente** | Recuerda información entre sesiones via `MEMORY.md` |
| 🎭 **Personalidades (SOULs)** | Cambia de rol en cualquier momento: dev, ejecutivo, o el que crees |
| 📅 **Tareas programadas** | Cron integrado con tres tipos: notificación, respuesta del LLM, o shell |
| 🛠️ **Herramientas del sistema** | Ejecuta comandos, lee ficheros, abre apps, inspecciona el sistema |
| 🎙️ **Audio y voz** | Transcripción automática de notas de voz y audios con Whisper local |
| 📄 **Documentos** | Procesa PDFs, imágenes y ficheros de texto enviados por Telegram |
| 🖼️ **Generación de imágenes** | Si el modelo genera imágenes, las guarda en `downloads/` y las envía por Telegram |
| 🔊 **Voz clonada (TTS)** | Responde con tu propia voz clonada usando Coqui XTTS-v2, 100% local |
| 🔒 **Seguridad** | Filtro de comandos peligrosos en dos niveles |
| 📱 **Telegram** | Bot completo con los mismos comandos que la terminal |

---

## 🚀 Instalación

### Requisitos

- Python 3.9+
- [LM Studio](https://lmstudio.ai), [Ollama](https://ollama.com) o [OpenRouter](https://openrouter.ai) como backend LLM
- Token de bot de Telegram (opcional, solo si usas el modo Telegram)

### 1 — Clonar y configurar

```bash
git clone https://github.com/TU_USUARIO/TU_REPO.git
cd TU_REPO
```

Edita `start.sh` con tus datos:

```bash
nano start.sh   # o abre con tu editor favorito
```

Las variables esenciales:

```bash
export TELEGRAM_TOKEN="TU_TOKEN_AQUI"     # de @BotFather en Telegram
export TELEGRAM_ALLOWED_USERS="123456789" # tu ID de Telegram (@userinfobot)
export AGENT_MODE="both"                  # terminal | telegram | both
```

### 2 — Instalar dependencias

```bash
chmod +x setup.sh
./setup.sh
```

Esto crea un entorno virtual `.venv` e instala todo automáticamente.

### 3 — Activar el backend LLM

**Opción A — LM Studio:**
1. Abre LM Studio
2. Ve a la pestaña **Local Server** (icono `<->`)
3. Pulsa **Start Server**
4. Carga el modelo que quieras usar

**Opción B — Ollama:**
```bash
ollama serve              # inicia el servidor (si no está ya activo)
ollama pull llama3.2      # descarga el modelo que quieras usar
```
Luego en `start.sh` cambia `BACKEND="ollama"`.

**Opción C — OpenRouter:**
1. Crea una cuenta en [openrouter.ai](https://openrouter.ai) y obtén tu API key
2. En `start.sh` configura:
```bash
export BACKEND="openrouter"
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="mistralai/mistral-7b-instruct"
```
Puedes ver todos los modelos disponibles en [openrouter.ai/models](https://openrouter.ai/models).

### 4 — Arrancar

```bash
chmod +x start.sh
./start.sh
```

---

## 📁 Estructura del proyecto

```
asistente/
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
├── downloads/            # 🖼️  Ficheros generados por el LLM (imágenes, docs)
│
└── core/
    ├── database.py       # 🗃️  Historial en SQLite
    ├── lmstudio.py       # 🔌 Cliente LM Studio API
    ├── commands.py       # ⌨️  Comandos slash (terminal)
    ├── cron_manager.py   # ⏰ Gestor de tareas programadas
    ├── telegram_bot.py   # 📱 Bot de Telegram
    ├── tools.py          # 🛠️  Herramientas del sistema
    ├── transcriber.py    # 🎙️  Transcripción de audio (Whisper)
    ├── downloads.py      # 🖼️  Gestión de ficheros generados por el LLM
    └── tts_engine.py     # 🔊 Síntesis de voz con clonación (Coqui XTTS-v2)
```

---

## ⌨️ Comandos

Los mismos comandos funcionan en terminal y en Telegram.

### Modelo

| Comando | Descripción |
|---|---|
| `/list` | Lista los modelos disponibles en LM Studio |
| `/load <modelo>` | Carga un modelo |
| `/unload` | Descarga el modelo activo |
| `/status` | Estado actual: modelo, sesión, soul activo |
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
| `/sessions-del <id>` | Borra una sesión por ID |
| `/sessions-clear` | Borra todas las sesiones excepto la actual |

### SOULs — personalidades

| Comando | Descripción |
|---|---|
| `/souls` | Lista las personalidades disponibles |
| `/soul <nombre>` | Cambia de personalidad |
| `/soul` | Vuelve a la personalidad por defecto |

Crea tus propias personalidades añadiendo ficheros `.md` en la carpeta `souls/`. El contenido del fichero es el system prompt.

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

El cron es interno, no usa el cron del sistema. Las tareas sobreviven a reinicios mientras el fichero `cron_jobs.json` exista.

**Tres tipos de tarea:**

```bash
/cron 09:00 Buenos días                        # 🔔 Notificación de texto fijo
/cron */1h llm: Resume las tareas pendientes   # 🤖 El LLM genera el mensaje
/cron 23:00 shell: ~/backup.sh                 # ⚙️  Ejecuta un script
```

**Formatos de horario:** `HH:MM` (diario) · `*/Nm` (cada N minutos) · `*/Nh` (cada N horas)

| Comando | Descripción |
|---|---|
| `/cron-list` | Lista las tareas activas |
| `/cron-del <id>` | Elimina una tarea |

### General

| Comando | Descripción |
|---|---|
| `/help` / `/ayuda` | Ayuda completa |
| `/exit` | Cierra el asistente |
| `/voz on\|off` | Activa o desactiva las respuestas por voz clonada |

---

## 🖼️ Generación de imágenes y documentos

Si usas un modelo con capacidades de generación de imágenes (como modelos multimodales
compatibles con LM Studio u Ollama), el asistente detecta automáticamente los ficheros
generados en la respuesta y los gestiona sin configuración adicional.

- Los ficheros se guardan en la carpeta `downloads/` con nombre y timestamp
- En Telegram se envían directamente al chat como imagen o documento
- En terminal se muestra la ruta del fichero guardado
- Soporta imágenes PNG, JPEG, WebP, GIF y documentos PDF

---

## 🔊 Voz clonada (TTS)

El asistente puede responder con tu propia voz clonada usando [Coqui XTTS-v2](https://github.com/coqui-ai/TTS), completamente en local.

**Configuración:**

1. Graba un audio de tu voz de al menos 10-30 segundos en formato WAV y ponlo en el directorio raíz del agente (junto a `agent.py`)
2. En `start.sh` configura:
```bash
export TTS_VOICE_SAMPLE="voz_origen.wav"   # nombre del fichero WAV de muestra
export TTS_LANGUAGE="es"                    # idioma de síntesis
```
3. Instala las dependencias de voz (requiere Python 3.10, descarga ~2GB):
```bash
./setup.sh --voz
```
4. Activa la voz desde Telegram con `/voz on` y desactívala con `/voz off`

La primera vez que se use tardará unos segundos en cargar el modelo XTTS-v2. Las siguientes respuestas son más rápidas.

> **Nota:** Los mensajes internos de Coqui TTS están suprimidos. Cuando la voz está activa el bot muestra `🔊 Generando audio...` mientras sintetiza y envía únicamente la nota de voz, sin texto.

---

## 🎙️ Audio y voz

En Telegram, el asistente transcribe automáticamente cualquier nota de voz o fichero de audio usando [faster-whisper](https://github.com/SYSTRAN/faster-whisper), que corre completamente local.

Muestra la transcripción y responde al contenido, como si hubieras escrito el mensaje.

**Modelos disponibles** (configurar en `start.sh`):

| Modelo | Tamaño | Velocidad | Precisión |
|---|---|---|---|
| `tiny` | ~75 MB | ⚡⚡⚡ | ★★☆☆ |
| `base` | ~145 MB | ⚡⚡ | ★★★☆ |
| `small` | ~466 MB | ⚡ | ★★★★ |
| `medium` | ~1.5 GB | 🐢 | ★★★★★ |

El modelo se descarga automáticamente la primera vez que se usa.

---

## 🔒 Seguridad en comandos de shell

Los comandos se filtran en dos niveles antes de ejecutarse:

**Bloqueados siempre** — ni con confirmación:
`rm`, `sudo`, `shutdown`, `reboot`, `mkfs`, `dd`, `killall`, escritura en `/etc/`, `/boot/`, `/System/`...

**Requieren confirmación** — solo en terminal, bloqueados en Telegram:
`kill`, `pip install`, `brew install`, `apt install`, `systemctl`, `crontab`...

---

## ⚙️ Configuración (start.sh)

| Variable | Por defecto | Descripción |
|---|---|---|
| `BACKEND` | `lmstudio` | Backend LLM: `lmstudio`, `ollama` o `openrouter` |
| `TELEGRAM_TOKEN` | — | Token del bot (de @BotFather) |
| `TELEGRAM_ALLOWED_USERS` | vacío (todos) | IDs de usuario separados por coma |
| `TELEGRAM_MAX_FILE_MB` | `20` | Tamaño máximo de fichero |
| `LMSTUDIO_HOST` | `http://localhost:1234` | URL del servidor LM Studio |
| `OLLAMA_HOST` | `http://localhost:11434` | URL del servidor Ollama |
| `OPENROUTER_API_KEY` | — | API key de OpenRouter (openrouter.ai/keys) |
| `OPENROUTER_MODEL` | — | Modelo a usar, ej: `mistralai/mistral-7b-instruct` |
| `LMSTUDIO_DEFAULT_MODEL` | vacío (autodetectar) | Modelo al arrancar |
| `LMSTUDIO_MAX_TOKENS` | `2048` | Tokens máximos por respuesta |
| `LMSTUDIO_TEMPERATURE` | `0.7` | Temperatura del modelo |
| `LMSTUDIO_CONTEXT_MESSAGES` | `30` | Mensajes de historial enviados al LLM |
| `AGENT_MODE` | `terminal` | `terminal` · `telegram` · `both` |
| `AGENT_LOG_LEVEL` | `WARNING` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `TTS_ENABLED` | `false` | Activar respuesta por voz: `true` o `false` |
| `TTS_VOICE_SAMPLE` | — | Ruta al WAV de muestra de tu voz |
| `TTS_LANGUAGE` | `es` | Idioma de síntesis: `es`, `en`, `fr`... |
| `TTS_DEVICE` | `cpu` | `cpu` o `cuda` (GPU) |
| `WHISPER_MODEL` | `base` | Modelo de transcripción de audio |
| `WHISPER_DEVICE` | `cpu` | `cpu` o `cuda` (GPU) |
| `WHISPER_LANGUAGE` | vacío (auto) | Código de idioma: `es`, `en`, `fr`... |

---

## 🛠️ Dependencias

| Paquete | Uso |
|---|---|
| `httpx` | Comunicación con LM Studio |
| `rich` | Terminal con colores y tablas |
| `python-telegram-bot` | Bot de Telegram |
| `pypdf` | Extracción de texto de PDFs |
| `faster-whisper` | Transcripción de audio local |

---

## 📝 Licencia

GPL-3.0 — puedes usar, modificar y distribuir este software, pero cualquier obra derivada debe publicarse bajo la misma licencia. Ver [LICENSE](LICENSE) para más detalles.
