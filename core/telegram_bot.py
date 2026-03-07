"""
telegram_bot.py — Bot de Telegram para el agente conversacional
Soporta: texto, imágenes, documentos PDF, y comandos slash.
"""

import os
import io
import asyncio
import logging
import tempfile
import base64
from datetime import datetime
from pathlib import Path

import httpx
from telegram import Update, BotCommand, constants
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from core import database, lmstudio
from core.cron_manager import CronManager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent  # raiz del agente, no core/
SOUL_PATH = BASE_DIR / "SOUL.md"
MEMORY_PATH = BASE_DIR / "MEMORY.md"


# ── Utilidades ────────────────────────────────────────────────────────────────

def load_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def build_system_prompt(soul_path=None) -> str:
    soul = load_file(Path(soul_path) if soul_path else SOUL_PATH)
    memory = load_file(MEMORY_PATH)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = ["# Fecha y hora actual\n" + now]
    if soul:
        parts.append(soul)
    if memory:
        parts.append("\n---\n# Memoria persistente\n" + memory)
    return "\n\n".join(parts)


def get_allowed_users() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
    if not raw:
        return set()  # vacío = todos permitidos
    return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


def is_allowed(user_id: int) -> bool:
    allowed = get_allowed_users()
    return not allowed or user_id in allowed


def max_file_mb() -> int:
    return int(os.environ.get("TELEGRAM_MAX_FILE_MB", "20"))


async def download_telegram_file(bot, file_id: str) -> bytes:
    """Descarga un fichero de Telegram y devuelve los bytes."""
    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    return buf.getvalue()


def encode_image_b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("utf-8")


# ── Estado por usuario ────────────────────────────────────────────────────────
# Cada user_id tiene su propio estado: {session_id, model}
_user_state: dict[int, dict] = {}


def get_user_state(user_id: int) -> dict:
    if user_id not in _user_state:
        model = lmstudio.get_loaded_model()
        session_id = database.new_session(model=model, label=f"telegram:{user_id}")
        _user_state[user_id] = {"session_id": session_id, "model": model, "soul_path": SOUL_PATH, "soul_name": "SOUL.md (por defecto)"}
    return _user_state[user_id]


# ── Manejadores de comandos Telegram ─────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return
    await update.message.reply_text(
        "🤖 *Agente LM Studio activo*\n\n"
        "Puedes enviarme:\n"
        "• Mensajes de texto\n"
        "• Imágenes (jpg, png, webp)\n"
        "• Documentos PDF\n"
        "• Ficheros de texto\n\n"
        "Comandos disponibles: /help",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = (
        "📋 *Comandos disponibles*\n\n"
        "*Modelo*\n"
        "/list — Modelos en LM Studio\n"
        "/load `<model>` — Cargar modelo\n"
        "/unload `[model]` — Descargar modelo de memoria\n"
        "/status — Estado y estadisticas\n"
        "/reset — Resetear contexto\n"
        "\n*Memoria y contexto*\n"
        "/memory `<texto>` — Guardar en memoria\n"
        "/compact — Resumir y compactar contexto\n"
        "/search `<texto>` — Buscar en el historial\n"
        "\n*Personalidades*\n"
        "/souls — Ver SOULs disponibles\n"
        "/soul `<nombre>` — Cambiar personalidad\n"
        "/soul — Volver al SOUL por defecto\n"
        "\n*Herramientas del sistema*\n"
        "/run `<cmd>` — Ejecutar comando de shell\n"
        "/open `<app>` — Abrir aplicacion o fichero\n"
        "/read `<ruta>` — Leer fichero\n"
        "/ls `[ruta]` — Listar directorio\n"
        "/sysinfo — Info del sistema\n"
        "/download `<ruta>` — Enviar fichero al chat\n"
        "\n*Cron — tareas programadas*\n"
        "/cron `<horario>` `<texto>` — 🔔 Notificacion de texto fijo\n"
        "/cron `<horario>` `llm: <prompt>` — 🤖 El LLM genera el mensaje\n"
        "/cron `<horario>` `shell: <cmd>` — ⚙️ Ejecuta un comando o script\n"
        "_Horario:_ `HH:MM` | `*/Nm` | `*/Nh`\n"
        "_Ej:_ `/cron 09:00 Buenos dias`\n"
        "_Ej:_ `/cron */1h llm: Dame un consejo aleatorio`\n"
        "_Ej:_ `/cron 08:00 shell: ~/scripts/backup.sh`\n"
        "/cronlist — Ver tareas (con icono de tipo)\n"
        "/crondel `<id>` — Eliminar tarea\n"
        "\n*General*\n"
        "/sessions — Ultimas sesiones\n"
        "/sessionsdel `<id>` — Borrar sesion por ID\n"
        "/sessionsclear — Borrar todas excepto la actual\n"
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    try:
        models = lmstudio.list_models()
        if not models:
            await update.message.reply_text("ℹ️ No hay modelos disponibles en LM Studio.")
            return
        lines = ["📦 *Modelos disponibles:*\n"]
        for m in models:
            lines.append(f"• `{m.get('id', '-')}`")
        await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error conectando con LM Studio:\n`{e}`",
                                        parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_load(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    args = ctx.args
    if not args:
        await update.message.reply_text("Uso: /load `<model_id>`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    model_id = " ".join(args)
    msg = await update.message.reply_text(f"⏳ Cargando `{model_id}`...", parse_mode=constants.ParseMode.MARKDOWN)
    ok = lmstudio.load_model(model_id)
    if ok:
        state["model"] = model_id
        database.update_session_model(state["session_id"], model_id)
        await msg.edit_text(f"✅ Modelo cargado: `{model_id}`", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await msg.edit_text(f"❌ No se pudo cargar `{model_id}`. Verifica el ID en /list",
                            parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    stats = database.get_stats(state["session_id"])
    try:
        models = lmstudio.list_models()
        lm_status = f"✅ conectado ({len(models)} modelo(s))"
    except Exception:
        lm_status = "❌ sin conexión"

    text = (
        f"📊 *Estado del Agente*\n\n"
        f"👤 Usuario: `{uid}`\n"
        f"🔢 Sesión: `{stats['session_id']}`\n"
        f"🤖 Modelo: `{state.get('model') or 'ninguno'}`\n"
        f"💬 Mensajes: `{stats['total_messages']}`\n"
        f"🔤 Tokens: `{stats['total_tokens']}`\n"
        f"🌐 LM Studio: {lm_status}\n"
        f"🕐 Ahora: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    state["session_id"] = database.new_session(model=state.get("model"), label=f"telegram:{uid}")
    await update.message.reply_text("♻️ Contexto reseteado. Nueva sesión iniciada.")


async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text("Uso: /memory `<texto a recordar>`",
                                        parse_mode=constants.ParseMode.MARKDOWN)
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n- [{timestamp}] {text}\n"
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    await update.message.reply_text(f"✅ Guardado en memoria:\n_{text}_",
                                    parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_cron(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cron: CronManager):
    if not is_allowed(update.effective_user.id):
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "*Uso:* `/cron <horario> <accion>`\n\n"
            "*Tipos de accion:*\n"
            "Texto fijo: `/cron 09:00 Buenos dias`\n"
            "LLM genera msg: `/cron */1h llm: Consejo de productividad`\n"
            "Ejecutar comando: `/cron 08:00 shell: ~/scripts/backup.sh`\n\n"
            "*Formatos de horario:* `HH:MM` | `*/Nm` | `*/Nh`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    from core.cron_manager import JOB_NOTIFY, JOB_LLM, JOB_SHELL
    schedule = ctx.args[0]
    action = " ".join(ctx.args[1:])
    chat_id = update.effective_chat.id

    if action.lower().startswith("llm:"):
        job_type = JOB_LLM
        action = action[4:].strip()
        icon = "🤖"
        type_label = "LLM"
    elif action.lower().startswith("shell:"):
        job_type = JOB_SHELL
        action = action[6:].strip()
        icon = "⚙️"
        type_label = "Shell"
    else:
        job_type = JOB_NOTIFY
        icon = "🔔"
        type_label = "Notificacion"

    # Para tareas llm, guardar en el historial del usuario que crea la tarea
    sid = state.get('session_id') if job_type == JOB_LLM else None
    job_id = cron.add_job(schedule, action, job_type=job_type,
                          telegram_chat_id=chat_id, session_id=sid)
    if job_id:
        await update.message.reply_text(
            icon + " Tarea programada (ID: `" + str(job_id) + "`) [" + type_label + "]\n_" + action + "_ -> `" + schedule + "`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("Formato de horario invalido. Usa `HH:MM`, `*/Nm` o `*/Nh`",
            parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_cronlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cron: CronManager):
    if not is_allowed(update.effective_user.id):
        return
    jobs = cron.list_jobs()
    if not jobs:
        await update.message.reply_text("ℹ️ No hay tareas programadas.")
        return
    type_icons = {"notify": "🔔", "llm": "🤖", "shell": "⚙️"}
    lines = ["⏰ *Tareas programadas:*\n"]
    for j in jobs:
        icon = type_icons.get(j.get("type", "notify"), "🔔")
        lines.append(icon + " ID `" + str(j["id"]) + "` | `" + j["schedule"] + "` | _" + j["action"] + "_")
        lines.append("  Proxima: `" + j.get("next_run", "-")[:16] + "`")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_crondel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cron: CronManager):
    if not is_allowed(update.effective_user.id):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Uso: /crondel `<id>`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    job_id = int(ctx.args[0])
    ok = cron.remove_job(job_id)
    if ok:
        await update.message.reply_text(f"✅ Tarea `{job_id}` eliminada.", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ No existe tarea con ID `{job_id}`.",
                                        parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_sessions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    sessions = database.list_sessions(8)
    if not sessions:
        await update.message.reply_text("ℹ️ No hay sesiones previas.")
        return
    lines = ["📚 *Últimas sesiones:*\n"]
    for s in sessions:
        lines.append(f"• ID `{s['id']}` | {s['created_at'][:16]} | {s['total_messages'] or 0} msgs")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


# ── Comandos faltantes ───────────────────────────────────────────────────────

async def cmd_unload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    model_id = " ".join(ctx.args) if ctx.args else state.get("model")
    if not model_id:
        await update.message.reply_text("No hay modelo activo que descargar.")
        return
    msg = await update.message.reply_text("Descargando `" + model_id + "`...", parse_mode=constants.ParseMode.MARKDOWN)
    ok, result = lmstudio.unload_model(model_id)
    if ok:
        state["model"] = None
        await msg.edit_text("Modelo descargado: `" + result + "`\nUsa /list y /load para cargar otro.", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await msg.edit_text("No se pudo descargar via API: " + result + "\nPrueba desde la interfaz de LM Studio.")


async def cmd_compact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    if not state.get("model"):
        await update.message.reply_text("Sin modelo activo.")
        return
    history = database.get_history(state["session_id"], limit=100)
    if not history:
        await update.message.reply_text("No hay historial que compactar.")
        return
    msg = await update.message.reply_text("Generando resumen del contexto...")
    conversation = "\n".join(m["role"].upper() + ": " + m["content"] for m in history)
    summary_prompt = (
        "Resume la siguiente conversacion en un parrafo breve y concreto, "
        "extrayendo los puntos clave, decisiones tomadas y contexto importante. "
        "Responde SOLO con el resumen, sin preambulos.\n\nCONVERSACION:\n" + conversation[:6000]
    )
    try:
        summary, _ = lmstudio.chat(model=state["model"],
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.3, max_tokens=400)
    except Exception as e:
        await msg.edit_text("Error generando resumen: " + str(e))
        return
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime("%Y-%m-%d %H:%M")
    entry = "\n## Resumen de sesion [" + timestamp + "]\n" + summary.strip() + "\n"
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    database.save_session_summary(state["session_id"], summary.strip())
    state["session_id"] = database.new_session(model=state.get("model"), label="telegram:" + str(uid))
    await msg.edit_text("*Contexto compactado*\n\n" + summary.strip(), parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    query = " ".join(ctx.args) if ctx.args else ""
    if not query:
        await update.message.reply_text("Uso: /search <texto>")
        return
    results = database.search_messages(query, limit=10)
    if not results:
        await update.message.reply_text("Sin resultados para: " + query)
        return
    lines = ["*Resultados para \"" + query + "\":*\n"]
    for r in results:
        content = r["content"]
        idx = content.lower().find(query.lower())
        start = max(0, idx - 30)
        end = min(len(content), idx + len(query) + 60)
        fragment = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
        lines.append("Sesion `" + str(r["session_id"]) + "` | " + r["timestamp"][:16] + " | _" + r["role"] + "_")
        lines.append("`" + fragment.replace("`", "'") + "`\n")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_souls(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    from pathlib import Path as _Path
    souls_dir = BASE_DIR / "souls"
    souls_dir.mkdir(exist_ok=True)
    souls = list(souls_dir.glob("*.md"))
    lines = ["*SOULs disponibles:*\n", "- `default` - SOUL.md (por defecto)"]
    for s in sorted(souls):
        lines.append("- `" + s.stem + "` - " + s.name)
    lines.append("\nUso: /soul <nombre>  |  /soul para volver al por defecto")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_soul_change(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    souls_dir = BASE_DIR / "souls"
    name = " ".join(ctx.args).strip() if ctx.args else ""

    if not name or name == "default":
        state["soul_path"] = BASE_DIR / "SOUL.md"
        state["soul_name"] = "SOUL.md (por defecto)"
        await update.message.reply_text("✅ Soul activo: SOUL.md (por defecto)")
        return

    candidates = [souls_dir / (name + ".md"), souls_dir / name]
    found = next((p for p in candidates if p.exists()), None)
    if not found:
        await update.message.reply_text(
            "Soul `" + name + "` no encontrado.\nUsa /souls para ver los disponibles.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    state["soul_path"] = found
    state["soul_name"] = found.name
    await update.message.reply_text("✅ Soul activo: " + found.name)


def _tg_soul_preview(path) -> str:
    """Devuelve las primeras lineas utiles del soul como texto plano."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        # Quitar prefijos markdown (#, -, *) para texto limpio
        clean = []
        for l in lines:
            stripped = l.strip().lstrip("#").lstrip("-").lstrip("*").strip()
            if stripped:
                clean.append(stripped)
        preview = "\n".join(clean[:6])
        if len(clean) > 6:
            preview += "\n...(" + str(len(lines)) + " lineas en total)"
        return preview
    except Exception:
        return "(no se pudo leer el soul)"


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    cmd_str = " ".join(ctx.args) if ctx.args else ""
    if not cmd_str:
        await update.message.reply_text("Uso: /run <comando>")
        return
    from core.tools import run_shell, is_blocked
    blocked, pattern = is_blocked(cmd_str)
    if blocked:
        await update.message.reply_text(
            "Comando bloqueado por seguridad: `" + pattern + "`\n"
            "Los comandos rm, mv, sudo y otros destructivos no se pueden ejecutar.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
    msg = await update.message.reply_text("Ejecutando `" + cmd_str + "`...", parse_mode=constants.ParseMode.MARKDOWN)
    code, out, err = run_shell(cmd_str, require_confirm=False)
    output = (out or "") + ("\n" + err if err else "")
    output = output.strip() or "(sin salida)"
    if len(output) > 3500:
        output = output[:3500] + "\n..."
    status = "OK" if code == 0 else "Error (codigo " + str(code) + ")"
    await msg.edit_text(status + "\n```\n" + output + "\n```", parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_open_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    app_name = " ".join(ctx.args) if ctx.args else ""
    if not app_name:
        await update.message.reply_text("Uso: /open <app o ruta>")
        return
    from core.tools import open_app
    ok, result = open_app(app_name)
    await update.message.reply_text(("OK: " if ok else "Error: ") + result)


async def cmd_read(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    path_str = " ".join(ctx.args) if ctx.args else ""
    if not path_str:
        await update.message.reply_text("Uso: /read <ruta>")
        return
    from core.tools import read_file
    ok, content = read_file(path_str)
    if ok:
        if len(content) > 3500:
            content = content[:3500] + "\n..."
        await update.message.reply_text("`" + path_str + "`\n```\n" + content + "\n```", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Error: " + content)


async def cmd_ls(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    path_str = " ".join(ctx.args) if ctx.args else "."
    from core.tools import list_directory
    ok, output = list_directory(path_str)
    if ok:
        if len(output) > 3500:
            output = output[:3500] + "\n..."
        await update.message.reply_text("```\n" + output + "\n```", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Error: " + output)


async def cmd_sysinfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    from core.tools import get_system_info
    await update.message.reply_text("*Info del sistema*\n\n```\n" + get_system_info() + "\n```", parse_mode=constants.ParseMode.MARKDOWN)




async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /download <ruta>  — Envía un fichero del servidor al chat de Telegram.
    Soporta cualquier tipo de fichero. Limite: definido en TELEGRAM_MAX_FILE_MB.
    """
    if not is_allowed(update.effective_user.id):
        return

    path_str = " ".join(ctx.args).strip() if ctx.args else ""
    if not path_str:
        await update.message.reply_text(
            "Uso: /download `<ruta>`\n\nEjemplos:\n"
            "`/download ~/Desktop/informe.pdf`\n"
            "`/download /tmp/resultado.txt`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    import os
    from pathlib import Path

    file_path = Path(path_str).expanduser().resolve()

    # Comprobaciones
    if not file_path.exists():
        await update.message.reply_text(f"El fichero no existe: `{path_str}`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    if not file_path.is_file():
        await update.message.reply_text(f"`{path_str}` es un directorio, no un fichero.\nUsa /ls para listar su contenido.", parse_mode=constants.ParseMode.MARKDOWN)
        return

    max_bytes = max_file_mb() * 1024 * 1024
    file_size = file_path.stat().st_size
    if file_size > max_bytes:
        size_mb = file_size / (1024 * 1024)
        await update.message.reply_text(
            f"Fichero demasiado grande: `{size_mb:.1f} MB` (maximo {max_file_mb()} MB).\n"
            "Puedes cambiar el limite en `TELEGRAM_MAX_FILE_MB` en start.sh.",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text(f"Preparando `{file_path.name}`...", parse_mode=constants.ParseMode.MARKDOWN)

    try:
        with open(file_path, "rb") as f:
            caption = f"`{file_path}`"
            await update.message.reply_document(
                document=f,
                filename=file_path.name,
                caption=caption,
                parse_mode=constants.ParseMode.MARKDOWN
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Error enviando el fichero: {e}")



async def cmd_sessions_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    if not ctx.args:
        await update.message.reply_text("Uso: /sessionsdel `<id>`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    try:
        session_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser un numero.")
        return
    if session_id == state.get("session_id"):
        await update.message.reply_text("No puedes borrar la sesion activa. Usa /reset primero.")
        return
    ok = database.delete_session(session_id)
    if ok:
        await update.message.reply_text(f"✅ Sesion `{session_id}` eliminada.", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"No se encontro la sesion `{session_id}`.", parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_sessions_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    current = state.get("session_id")
    count = database.delete_all_sessions_except(current)
    await update.message.reply_text(
        f"✅ {count} sesion(es) eliminadas.\nSesion actual (`{current}`) conservada.",
        parse_mode=constants.ParseMode.MARKDOWN
    )


# ── Manejador de mensajes de texto ────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    uid = update.effective_user.id
    state = get_user_state(uid)

    if not state.get("model"):
        await update.message.reply_text(
            "⚠️ No hay modelo activo. Usa /list y /load `<model>`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    user_text = update.message.text
    await _respond(update, state, user_text)


# ── Manejador de imágenes ─────────────────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    uid = update.effective_user.id
    state = get_user_state(uid)

    if not state.get("model"):
        await update.message.reply_text("⚠️ No hay modelo activo. Usa /list y /load `<model>`",
                                        parse_mode=constants.ParseMode.MARKDOWN)
        return

    caption = update.message.caption or "Describe esta imagen."
    msg = await update.message.reply_text("🖼️ Procesando imagen...")

    try:
        # Descargar la foto de mayor resolución
        photo = update.message.photo[-1]
        data = await download_telegram_file(ctx.bot, photo.file_id)

        # Construir mensaje multimodal
        user_content = [
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{encode_image_b64(data)}"
            }},
            {"type": "text", "text": caption},
        ]

        await _respond_multimodal(update, state, user_content, caption, msg)

    except Exception as e:
        logger.exception("Error procesando imagen")
        await msg.edit_text(f"❌ Error procesando la imagen: {e}")


# ── Manejador de documentos ───────────────────────────────────────────────────

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    uid = update.effective_user.id
    state = get_user_state(uid)

    if not state.get("model"):
        await update.message.reply_text("⚠️ No hay modelo activo.", parse_mode=constants.ParseMode.MARKDOWN)
        return

    doc = update.message.document
    caption = update.message.caption or ""
    max_bytes = max_file_mb() * 1024 * 1024

    if doc.file_size and doc.file_size > max_bytes:
        await update.message.reply_text(
            f"❌ Fichero demasiado grande (máx. {max_file_mb()} MB)."
        )
        return

    msg = await update.message.reply_text(f"📄 Procesando `{doc.file_name}`...",
                                          parse_mode=constants.ParseMode.MARKDOWN)

    try:
        data = await download_telegram_file(ctx.bot, doc.file_id)
        mime = doc.mime_type or ""
        fname = doc.file_name or "documento"

        if "pdf" in mime or fname.lower().endswith(".pdf"):
            await _handle_pdf(update, state, data, caption, fname, msg)
        elif mime.startswith("image/") or any(fname.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
            await _handle_image_doc(update, state, data, mime, caption, msg)
        elif mime.startswith("text/") or any(fname.lower().endswith(ext) for ext in [".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".xml", ".yaml", ".yml"]):
            await _handle_text_doc(update, state, data, caption, fname, msg)
        else:
            # Intento genérico como texto
            try:
                text_content = data.decode("utf-8", errors="replace")
                prompt = f"Fichero: {fname}\n\n{text_content}"
                if caption:
                    prompt = f"{caption}\n\n{prompt}"
                await _respond(update, state, prompt, editing_msg=msg)
            except Exception:
                await msg.edit_text(
                    f"⚠️ No puedo procesar este tipo de fichero (`{mime}`).\n"
                    "Soportados: PDF, imágenes, texto, código.",
                    parse_mode=constants.ParseMode.MARKDOWN,
                )

    except Exception as e:
        logger.exception("Error procesando documento")
        await msg.edit_text(f"❌ Error procesando el fichero: {e}")



async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Procesa mensajes de voz (notas de voz de Telegram)."""
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    if not state.get("model"):
        await update.message.reply_text("Sin modelo activo.")
        return

    from core.transcriber import transcribe_bytes, is_available
    if not is_available():
        await update.message.reply_text(
            "faster-whisper no esta instalado.\n"
            "Ejecuta: `pip install faster-whisper`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text("🎙️ Transcribiendo audio...")
    try:
        voice = update.message.voice
        data = await download_telegram_file(ctx.bot, voice.file_id)
        text = transcribe_bytes(data, suffix=".ogg")
        if not text:
            await msg.edit_text("No se pudo extraer texto del audio.")
            return
        await msg.edit_text("🎙️ _" + text + "_", parse_mode=constants.ParseMode.MARKDOWN)
        await _respond(update, state, text)
    except Exception as e:
        logger.exception("Error transcribiendo voz")
        await msg.edit_text("Error transcribiendo el audio: " + str(e))


async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Procesa ficheros de audio enviados como documento de audio (mp3, m4a, wav, etc.)."""
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    state = get_user_state(uid)
    if not state.get("model"):
        await update.message.reply_text("Sin modelo activo.")
        return

    from core.transcriber import transcribe_bytes, is_available
    if not is_available():
        await update.message.reply_text(
            "faster-whisper no esta instalado.\n"
            "Ejecuta: `pip install faster-whisper`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    audio = update.message.audio
    fname = audio.file_name or "audio"
    suffix = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ".mp3"
    max_bytes = max_file_mb() * 1024 * 1024

    if audio.file_size and audio.file_size > max_bytes:
        await update.message.reply_text(
            "Fichero demasiado grande (max " + str(max_file_mb()) + " MB)."
        )
        return

    msg = await update.message.reply_text("🎵 Transcribiendo `" + fname + "`...",
                                          parse_mode=constants.ParseMode.MARKDOWN)
    try:
        data = await download_telegram_file(ctx.bot, audio.file_id)
        text = transcribe_bytes(data, suffix=suffix)
        if not text:
            await msg.edit_text("No se pudo extraer texto del audio.")
            return
        caption = update.message.caption or ""
        prompt = text if not caption else caption + "\n\nTranscripcion: " + text
        await msg.edit_text("🎵 _" + text + "_", parse_mode=constants.ParseMode.MARKDOWN)
        await _respond(update, state, prompt)
    except Exception as e:
        logger.exception("Error procesando audio")
        await msg.edit_text("Error procesando el audio: " + str(e))


async def _handle_pdf(update, state, data: bytes, caption: str, fname: str, msg):
    """Procesa un PDF — lo envía como documento base64 al LLM."""
    b64 = encode_image_b64(data)
    user_content = [
        {"type": "text", "text": caption or f"Analiza este PDF: {fname}"},
        # Formato compatible con modelos vision que aceptan PDF como imagen
        {"type": "image_url", "image_url": {
            "url": f"data:application/pdf;base64,{b64}"
        }},
    ]
    # Fallback: extraer texto del PDF con pypdf si está disponible
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        if text.strip():
            prompt = f"PDF: {fname}\n\n{text[:8000]}"
            if caption:
                prompt = f"{caption}\n\n{prompt}"
            await _respond(update, state, prompt, editing_msg=msg)
            return
    except ImportError:
        pass

    await _respond_multimodal(update, state, user_content, caption or fname, msg)


async def _handle_image_doc(update, state, data: bytes, mime: str, caption: str, msg):
    """Procesa una imagen enviada como documento."""
    if not mime or mime == "application/octet-stream":
        mime = "image/jpeg"
    b64 = encode_image_b64(data)
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": caption or "Describe esta imagen."},
    ]
    await _respond_multimodal(update, state, user_content, caption or "imagen", msg)


async def _handle_text_doc(update, state, data: bytes, caption: str, fname: str, msg):
    """Procesa un fichero de texto/código."""
    content = data.decode("utf-8", errors="replace")
    prompt = f"Fichero: `{fname}`\n\n```\n{content[:8000]}\n```"
    if caption:
        prompt = f"{caption}\n\n{prompt}"
    await _respond(update, state, prompt, editing_msg=msg)


# ── Respuesta al LLM ──────────────────────────────────────────────────────────


async def _respond(update: Update, state: dict, user_text: str, editing_msg=None):
    """Envía un mensaje de texto al LLM y responde al usuario."""
    system_prompt = build_system_prompt(state.get("soul_path"))
    history = database.get_history(
        state["session_id"],
        limit=int(os.environ.get("LMSTUDIO_CONTEXT_MESSAGES", "30"))
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    database.save_message(state["session_id"], "user", user_text)

    if editing_msg:
        await editing_msg.edit_text("💭 Pensando...")
    else:
        editing_msg = await update.message.reply_text("💭 Pensando...")

    try:
        response_text, tokens = lmstudio.chat(
            model=state["model"],
            messages=messages,
            temperature=float(os.environ.get("LMSTUDIO_TEMPERATURE", "0.7")),
            max_tokens=int(os.environ.get("LMSTUDIO_MAX_TOKENS", "2048")),
        )
        database.save_message(state["session_id"], "assistant", response_text, tokens)

        # Telegram tiene límite de 4096 chars por mensaje
        if len(response_text) > 4000:
            await editing_msg.edit_text(response_text[:4000])
            await update.message.reply_text(response_text[4000:])
        else:
            await editing_msg.edit_text(response_text)

    except Exception as e:
        logger.exception("Error en respuesta LLM")
        await editing_msg.edit_text(f"❌ Error: {e}\n¿LM Studio está activo?")


async def _respond_multimodal(update: Update, state: dict, user_content: list,
                               display_text: str, editing_msg):
    """Envía contenido multimodal al LLM."""
    system_prompt = build_system_prompt(state.get("soul_path"))
    history = database.get_history(state["session_id"], limit=10)  # Menos historial con multimedia
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    database.save_message(state["session_id"], "user", f"[multimedia] {display_text}")

    await editing_msg.edit_text("💭 Analizando...")

    try:
        response_text, tokens = lmstudio.chat(
            model=state["model"],
            messages=messages,
            temperature=float(os.environ.get("LMSTUDIO_TEMPERATURE", "0.7")),
            max_tokens=int(os.environ.get("LMSTUDIO_MAX_TOKENS", "2048")),
        )
        database.save_message(state["session_id"], "assistant", response_text, tokens)

        if len(response_text) > 4000:
            await editing_msg.edit_text(response_text[:4000])
            await update.message.reply_text(response_text[4000:])
        else:
            await editing_msg.edit_text(response_text)

    except Exception as e:
        logger.exception("Error en respuesta multimodal")
        await editing_msg.edit_text(f"❌ Error procesando el contenido: {e}")


# ── Arranque del bot ──────────────────────────────────────────────────────────


async def cmd_exit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("👋 Apagando el agente...")
    import os, signal
    os.kill(os.getpid(), signal.SIGTERM)


def build_application(cron: CronManager) -> Application:
    """Construye y configura la aplicación de Telegram."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_TOKEN no está configurado.")

    # Inyectar callback de cron para notificaciones Telegram
    cron.set_telegram_send_callback(_make_telegram_sender(token))

    app = Application.builder().token(token).build()

    # Comandos de texto
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("load", cmd_load))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("unload", cmd_unload))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("souls", cmd_souls))
    app.add_handler(CommandHandler("exit", cmd_exit))
    app.add_handler(CommandHandler("soul", cmd_soul_change))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("open", cmd_open_app))
    app.add_handler(CommandHandler("read", cmd_read))
    app.add_handler(CommandHandler("ls", cmd_ls))
    app.add_handler(CommandHandler("sysinfo", cmd_sysinfo))
    app.add_handler(CommandHandler("sessionsdel", cmd_sessions_del))
    app.add_handler(CommandHandler("sessionsclear", cmd_sessions_clear))
    app.add_handler(CommandHandler("download", cmd_download))

    # Cron con lambda para inyectar cron instance
    app.add_handler(CommandHandler("cron", lambda u, c: cmd_cron(u, c, cron)))
    app.add_handler(CommandHandler("cronlist", lambda u, c: cmd_cronlist(u, c, cron)))
    app.add_handler(CommandHandler("crondel", lambda u, c: cmd_crondel(u, c, cron)))

    # Mensajes de texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Imágenes
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Documentos (PDF, imágenes como doc, texto, código)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    return app


def _make_telegram_sender(token: str):
    """Devuelve una función async que envía mensajes a un chat_id de Telegram."""
    async def send(chat_id: int, text: str):
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
    return send


async def run_bot(cron: CronManager):
    """Arranca el bot en modo polling."""
    app = build_application(cron)

    # Registrar LLM en el cron para tareas de tipo llm:
    # Usar el modelo del primer usuario activo, o autodetectar
    from core.lmstudio import chat as _lm_chat, get_loaded_model as _get_model
    def _best_model():
        # Intentar modelo de cualquier usuario activo
        for uid, st in _user_state.items():
            if st.get("model"):
                return st["model"]
        return _get_model()
    cron.set_lmstudio(_lm_chat, _best_model)
    # Guardar mensajes del cron llm en el historial
    cron.set_context_callback(
        lambda sid, role, content: database.save_message(sid, role, content)
    )

    # Registrar comandos en BotFather automáticamente
    await app.bot.set_my_commands([
        BotCommand("help", "Ver todos los comandos"),
        BotCommand("list", "Modelos en LM Studio"),
        BotCommand("load", "Cargar modelo"),
        BotCommand("unload", "Descargar modelo de memoria"),
        BotCommand("status", "Estado y estadisticas"),
        BotCommand("reset", "Resetear contexto"),
        BotCommand("memory", "Guardar en memoria"),
        BotCommand("compact", "Resumir y compactar contexto"),
        BotCommand("search", "Buscar en el historial"),
        BotCommand("souls", "Ver personalidades disponibles"),
        BotCommand("exit", "Apagar el agente"),
        BotCommand("soul", "Cambiar personalidad"),
        BotCommand("run", "Ejecutar comando de shell"),
        BotCommand("open", "Abrir aplicacion o fichero"),
        BotCommand("read", "Leer fichero"),
        BotCommand("ls", "Listar directorio"),
        BotCommand("sysinfo", "Info del sistema"),
        BotCommand("download", "Descargar fichero del servidor"),
        BotCommand("cron", "Programar tarea"),
        BotCommand("cronlist", "Ver tareas programadas"),
        BotCommand("crondel", "Eliminar tarea"),
        BotCommand("sessions", "Ver sesiones anteriores"),
        BotCommand("sessionsdel", "Borrar una sesion por ID"),
        BotCommand("sessionsclear", "Borrar todas las sesiones excepto la actual"),
        BotCommand("start", "Iniciar el agente"),
    ])

    logger.info("🤖 Bot de Telegram iniciado.")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    # Mantener vivo hasta señal de parada
    await asyncio.Event().wait()
