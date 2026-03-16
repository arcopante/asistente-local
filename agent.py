#!/usr/bin/env python3
"""
agent.py — Agente conversacional principal
Modos: terminal | telegram | both
Configurado mediante variables de entorno (ver start.sh)
"""

import sys
import os
import signal
import asyncio
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint

sys.path.insert(0, str(Path(__file__).parent))

from core import database, llm_client
from core.commands import handle_command
from core.cron_manager import CronManager

console = Console()

# Nivel de log: WARNING por defecto (sin mensajes INFO ruidosos)
_log_level_str = os.environ.get("AGENT_LOG_LEVEL", "WARNING").upper()
_log_level = getattr(logging, _log_level_str, logging.WARNING)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
for _lib in ("httpx", "httpcore", "telegram", "telegram.ext", "apscheduler"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger("agent")

BASE_DIR  = Path(__file__).parent
SOUL_PATH = BASE_DIR / "SOUL.md"
MEMORY_PATH = BASE_DIR / "MEMORY.md"
SOULS_DIR = BASE_DIR / "souls"


def load_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def build_system_prompt(state: Optional[dict] = None) -> str:
    soul_path = (state or {}).get("soul_path", SOUL_PATH)
    soul   = load_file(Path(soul_path))
    memory = load_file(MEMORY_PATH)
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts  = ["# Fecha y hora actual\n" + now]
    if soul:
        parts.append(soul)
    if memory:
        parts.append("\n---\n# Memoria persistente\n" + memory)
    return "\n\n".join(parts)


def detect_model() -> Optional[str]:
    try:
        return llm_client.get_loaded_model()
    except Exception:
        return None


def cron_notify(message: str):
    console.print(Panel(message, style="bold yellow", title="🔔 Recordatorio"))


# ── Modo terminal ─────────────────────────────────────────────────────────────

def run_terminal(state: dict, cron: CronManager):
    console.print(Panel.fit(
        "[bold cyan]🤖 Asistente Local — Terminal[/bold cyan]\n"
        "[dim]Escribe /help para ver los comandos disponibles[/dim]",
        border_style="cyan"
    ))

    def _exit_handler(sig, frame):
        rprint("\n[yellow]👋 Saliendo...[/yellow]")
        cron.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _exit_handler)

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]Tú[/bold green]")
        except (EOFError, KeyboardInterrupt):
            rprint("\n[yellow]👋 Hasta luego.[/yellow]")
            cron.stop()
            break

        if not user_input.strip():
            continue

        if user_input.strip().startswith("/"):
            try:
                handle_command(user_input.strip(), state, cron)
            except SystemExit:
                cron.stop()
                break
            continue

        if not state.get("model"):
            rprint("[red]Sin modelo activo.[/red] Usa /list y /load <model>")
            continue

        system_prompt = build_system_prompt(state)
        history = database.get_history(
            state["session_id"],
            limit=int(os.environ.get("LMSTUDIO_CONTEXT_MESSAGES", "30"))
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        database.save_message(state["session_id"], "user", user_input)

        console.print("\n[bold blue]Agente[/bold blue] ", end="")
        response_text = ""
        try:
            for chunk in llm_client.chat_stream(
                model=state["model"],
                messages=messages,
                temperature=float(os.environ.get("LMSTUDIO_TEMPERATURE", "0.7")),
                max_tokens=int(os.environ.get("LMSTUDIO_MAX_TOKENS", "2048")),
            ):
                console.print(chunk, end="", markup=False)
                response_text += chunk
            console.print()

            # Detectar ficheros generados embebidos en la respuesta (data URIs)
            from core.downloads import extract_generated_files
            fake_response = {"choices": [{"message": {"content": response_text}}]}
            gen_files = extract_generated_files(fake_response)
            for f in gen_files:
                rprint(f"\n[green]📁 Fichero guardado:[/green] {f['path']}")

        except Exception as e:
            rprint(f"\n[red]Error:[/red] {e}")
            continue

        database.save_message(state["session_id"], "assistant", response_text)


# ── Modo Telegram ─────────────────────────────────────────────────────────────

async def run_telegram(cron: CronManager):
    from core.telegram_bot import run_bot
    loop = asyncio.get_event_loop()
    cron.set_event_loop(loop)
    await run_bot(cron)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # El backend se configura via variables de entorno en start.sh
    # BACKEND=lmstudio | ollama, LMSTUDIO_HOST, OLLAMA_HOST
    # llm_client.py lee estas variables dinamicamente en cada llamada

    database.init_db()
    SOULS_DIR.mkdir(exist_ok=True)

    state: dict = {
        "session_id": None,
        "model": None,
        "history": [],
        "soul_path": SOUL_PATH,
        "soul_name": "SOUL.md (por defecto)",
    }

    configured_model = os.environ.get("LMSTUDIO_DEFAULT_MODEL", "").strip()
    state["model"] = configured_model or detect_model()
    if state["model"]:
        logger.info("Modelo activo: " + state["model"])
    else:
        logger.warning("No se detecto modelo activo en LM Studio.")

    state["session_id"] = database.new_session(model=state["model"])

    cron = CronManager(notify_callback=cron_notify)
    from core.llm_client import chat as _lm_chat, get_loaded_model as _get_model
    cron.set_llm(_lm_chat, lambda: state.get("model") or _get_model())
    cron.set_context_callback(
        lambda sid, role, content: database.save_message(sid, role, content)
    )
    cron.start()

    mode = os.environ.get("AGENT_MODE", "terminal").lower()

    if mode == "telegram":
        asyncio.run(run_telegram(cron))

    elif mode == "both":
        import threading
        tg_thread = threading.Thread(
            target=lambda: asyncio.run(run_telegram(cron)),
            daemon=True,
            name="telegram-bot"
        )
        tg_thread.start()
        rprint("[dim]Bot de Telegram iniciado en segundo plano.[/dim]")
        run_terminal(state, cron)

    else:
        run_terminal(state, cron)


if __name__ == "__main__":
    main()
