"""
commands.py — Procesador de comandos slash del agente
Mejoras v3: herramientas del sistema, compactación de contexto, múltiples SOULs, búsqueda en historial.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import print as rprint

from core import llm_client, database
from core.cron_manager import CronManager

console = Console()

BASE_DIR = Path(__file__).parent.parent
SOUL_PATH = BASE_DIR / "SOUL.md"
MEMORY_PATH = BASE_DIR / "MEMORY.md"
SOULS_DIR = BASE_DIR / "souls"


def handle_command(cmd_line: str, state: dict, cron: CronManager) -> bool:
    parts = cmd_line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/list":
        _cmd_list()
    elif cmd == "/load":
        _cmd_load(arg, state)
    elif cmd == "/unload":
        _cmd_unload(arg, state)
    elif cmd == "/status":
        _cmd_status(state)
    elif cmd == "/reset":
        _cmd_reset(state)
    elif cmd == "/memory":
        _cmd_memory(arg)
    elif cmd == "/compact":
        _cmd_compact(state)
    elif cmd == "/search":
        _cmd_search(arg)
    elif cmd == "/soul":
        _cmd_soul(arg, state)
    elif cmd == "/souls":
        _cmd_souls()
    elif cmd == "/run":
        _cmd_run(arg)
    elif cmd == "/open":
        _cmd_open(arg)
    elif cmd == "/read":
        _cmd_read(arg)
    elif cmd == "/ls":
        _cmd_ls(arg)
    elif cmd == "/sysinfo":
        _cmd_sysinfo()
    elif cmd == "/cron":
        _cmd_cron(arg, cron)
    elif cmd == "/cron-list":
        _cmd_cron_list(cron)
    elif cmd == "/cron-del":
        _cmd_cron_del(arg, cron)
    elif cmd == "/sessions":
        _cmd_sessions()
    elif cmd == "/sessions-del":
        _cmd_sessions_del(arg, state)
    elif cmd == "/sessions-clear":
        _cmd_sessions_clear(state)
    elif cmd == "/help":
        _cmd_help()
    elif cmd in ("/exit", "/quit"):
        rprint("[yellow]Hasta luego.[/yellow]")
        raise SystemExit(0)
    else:
        rprint(f"[red]Comando desconocido:[/red] {cmd}. Escribe /help para ver los comandos.")
    return True


# ── Modelo ────────────────────────────────────────────────────────────────────

def _cmd_list():
    try:
        models = llm_client.list_models()
        if not models:
            rprint("[yellow]No hay modelos disponibles en el backend activo.[/yellow]")
            return
        table = Table(title="Modelos disponibles", show_lines=True)
        table.add_column("ID", style="cyan")
        table.add_column("Tipo", style="green")
        for m in models:
            table.add_row(m.get("id", "-"), m.get("object", "-"))
        console.print(table)
    except Exception as e:
        rprint(f"[red]Error conectando con el backend:[/red] {e}")


def _cmd_load(model_id: str, state: dict):
    if not model_id:
        rprint("[yellow]Uso: /load <model_id>[/yellow]")
        return
    rprint(f"[cyan]Cargando modelo [bold]{model_id}[/bold]...[/cyan]")
    ok = llm_client.load_model(model_id)
    if ok:
        state["model"] = model_id
        database.update_session_model(state["session_id"], model_id)
        rprint(f"[green]Modelo cargado:[/green] {model_id}")
    else:
        rprint("[red]No se pudo cargar el modelo.[/red] Verifica que el backend esta activo y el modelo existe.")


def _cmd_unload(arg: str, state: dict):
    """
    /unload          -> descarga el modelo activo
    /unload <model>  -> descarga un modelo concreto
    """
    model_id = arg.strip() or state.get("model") or None
    if model_id:
        rprint(f"[cyan]Descargando modelo [bold]{model_id}[/bold]...[/cyan]")
    else:
        rprint("[cyan]Descargando modelo activo...[/cyan]")

    ok, msg = llm_client.unload_model(model_id)
    if ok:
        rprint(f"[green]Modelo descargado:[/green] {msg}")
        if state.get("model") == msg or not arg:
            state["model"] = None
            rprint("[dim]Usa /list y /load <model> para cargar otro modelo.[/dim]")
    else:
        rprint(f"[yellow]No se pudo descargar via API:[/yellow] {msg}")
        rprint("  En Ollama prueba: ollama pull <modelo>. En LM Studio descargalo desde la interfaz.")


def _cmd_status(state: dict):
    stats = database.get_stats(state["session_id"])
    soul_name = state.get("soul_name", "SOUL.md (por defecto)")
    table = Table(title="Estado del Agente", show_lines=True)
    table.add_column("Parametro", style="cyan")
    table.add_column("Valor", style="white")
    table.add_row("Sesion ID", str(stats["session_id"]))
    table.add_row("Inicio sesion", stats["created_at"])
    table.add_row("Modelo activo", state.get("model") or "ninguno")
    table.add_row("Soul activo", soul_name)
    table.add_row("Mensajes sesion", str(stats["total_messages"]))
    table.add_row("Tokens usados", str(stats["total_tokens"]))
    table.add_row("Sesiones totales", str(stats["total_sessions_ever"]))
    table.add_row("Ahora", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    console.print(table)
    try:
        models = llm_client.list_models()
        from core.llm_client import backend_info
        rprint(f"[green]Backend:[/green] {backend_info()} — {len(models)} modelo(s)")
    except Exception:
        from core.llm_client import backend_info
        rprint("[red]Backend:[/red] " + backend_info() + " — sin conexion")


def _cmd_reset(state: dict):
    rprint("[yellow]Reseteando contexto...[/yellow]")
    state["history"] = []
    state["session_id"] = database.new_session(model=state.get("model"))
    rprint("[green]Contexto limpio. Nueva sesion iniciada.[/green]")
    rprint(f"[dim]Soul activo: {state.get('soul_name', 'por defecto')}[/dim]")


# ── Memoria y contexto ────────────────────────────────────────────────────────

def _cmd_memory(text: str):
    if not text:
        rprint("[yellow]Uso: /memory <texto a recordar>[/yellow]")
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = "\n- [" + timestamp + "] " + text + "\n"
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    rprint(f"[green]Guardado en MEMORY.md:[/green] {text}")


def _cmd_compact(state: dict):
    """Compacta el contexto: resume la conversacion, guarda en MEMORY.md y reinicia historial."""
    if not state.get("model"):
        rprint("[red]Sin modelo activo para compactar.[/red]")
        return

    history = database.get_history(state["session_id"], limit=100)
    if not history:
        rprint("[yellow]No hay historial que compactar.[/yellow]")
        return

    rprint("[cyan]Compactando contexto, generando resumen...[/cyan]")

    conversation = "\n".join(
        m["role"].upper() + ": " + m["content"] for m in history
    )
    summary_prompt = (
        "Resume la siguiente conversacion en un parrafo breve y concreto, "
        "extrayendo los puntos clave, decisiones tomadas y contexto importante. "
        "Responde SOLO con el resumen, sin preambulos.\n\nCONVERSACION:\n" +
        conversation[:6000]
    )

    try:
        summary, _ = llm_client.chat(
            model=state["model"],
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.3,
            max_tokens=400,
        )
    except Exception as e:
        rprint(f"[red]Error generando resumen:[/red] {e}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = "\n## Resumen de sesion [" + timestamp + "]\n" + summary.strip() + "\n"
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(entry)

    database.save_session_summary(state["session_id"], summary.strip())
    state["history"] = []
    state["session_id"] = database.new_session(model=state.get("model"))

    console.print(Panel(
        summary.strip(),
        title="[bold green]Resumen guardado en MEMORY.md[/bold green]",
        border_style="green"
    ))
    rprint("[green]Contexto compactado. Nueva sesion iniciada.[/green]")


def _cmd_search(query: str):
    """Busca en todo el historial de conversaciones."""
    if not query:
        rprint("[yellow]Uso: /search <texto a buscar>[/yellow]")
        return

    results = database.search_messages(query, limit=15)
    if not results:
        rprint(f"[yellow]Sin resultados para:[/yellow] {query}")
        return

    table = Table(
        title=f'Resultados para "{query}" ({len(results)} encontrados)',
        show_lines=True
    )
    table.add_column("Sesion", style="cyan", width=7)
    table.add_column("Fecha", style="dim", width=17)
    table.add_column("Rol", style="green", width=10)
    table.add_column("Fragmento", style="white")

    for r in results:
        content = r["content"]
        idx = content.lower().find(query.lower())
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(content), idx + len(query) + 80)
            fragment = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
        else:
            fragment = content[:120] + ("..." if len(content) > 120 else "")

        fragment_hl = fragment.replace(query, "[bold yellow]" + query + "[/bold yellow]")
        table.add_row(
            str(r["session_id"]),
            r["timestamp"][:16],
            r["role"],
            fragment_hl,
        )

    console.print(table)


# ── SOULs ─────────────────────────────────────────────────────────────────────

def _cmd_soul(name: str, state: dict):
    if not name:
        state["soul_path"] = SOUL_PATH
        state["soul_name"] = "SOUL.md (por defecto)"
        preview = _soul_preview(SOUL_PATH)
        console.print(Panel(preview, title="[green]Soul activo: SOUL.md (por defecto)[/green]", border_style="green"))
        return

    SOULS_DIR.mkdir(exist_ok=True)
    candidates = [SOULS_DIR / (name + ".md"), SOULS_DIR / name, BASE_DIR / (name + ".md")]
    found = next((p for p in candidates if p.exists()), None)

    if not found:
        rprint(f"[red]Soul no encontrado:[/red] {name}")
        rprint(f"  Crea el fichero [cyan]souls/{name}.md[/cyan] con el system prompt.")
        rprint("  Usa [bold]/souls[/bold] para ver los disponibles.")
        return

    state["soul_path"] = found
    state["soul_name"] = found.name
    preview = _soul_preview(found)
    console.print(Panel(preview, title=f"[green]Soul activo: {found.name}[/green]", border_style="green"))
    rprint("[dim]Se aplica a partir del siguiente mensaje.[/dim]")


def _soul_preview(path) -> str:
    """Devuelve las primeras lineas utiles del soul (sin cabeceras markdown vacias)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        useful = [l for l in lines if l.strip() and not l.strip() == "#"]
        preview_lines = useful[:6]
        preview = "\n".join(preview_lines)
        if len(useful) > 6:
            preview += f"\n[dim]... ({len(lines)} lineas en total)[/dim]"
        return preview
    except Exception:
        return "(no se pudo leer el soul)"


def _cmd_souls():
    SOULS_DIR.mkdir(exist_ok=True)
    souls = list(SOULS_DIR.glob("*.md"))

    table = Table(title="SOULs disponibles", show_lines=True)
    table.add_column("Nombre", style="cyan")
    table.add_column("Fichero", style="dim")
    table.add_column("Tamano", style="white")

    size = SOUL_PATH.stat().st_size if SOUL_PATH.exists() else 0
    table.add_row("(por defecto)", "SOUL.md", str(size) + " B")
    for s in sorted(souls):
        table.add_row(s.stem, str(s.relative_to(BASE_DIR)), str(s.stat().st_size) + " B")

    console.print(table)
    rprint("\n  Uso: [bold]/soul <nombre>[/bold]  —  [bold]/soul[/bold] para volver al por defecto")
    rprint(f"  Coloca nuevos SOULs en [cyan]souls/[/cyan] como ficheros .md")


# ── Herramientas del sistema ──────────────────────────────────────────────────

def _cmd_run(cmd: str):
    if not cmd:
        rprint("[yellow]Uso: /run <comando>[/yellow]")
        rprint("  Ejemplo: /run ls -la ~/Desktop")
        return
    from core.tools import run_shell, format_shell_result, is_blocked, needs_confirm as _needs_confirm
    blocked, pattern = is_blocked(cmd)
    if blocked:
        rprint("[bold red]Comando bloqueado:[/bold red] " + pattern)
        rprint("[red]Los comandos rm, mv, sudo y otros destructivos estan prohibidos.[/red]")
        return
    code, out, err = run_shell(cmd, require_confirm=_needs_confirm(cmd))
    result = format_shell_result(cmd, code, out, err)
    if result:
        rprint(result)


def _cmd_open(app: str):
    if not app:
        rprint("[yellow]Uso: /open <aplicacion o ruta>[/yellow]")
        return
    from core.tools import open_app
    ok, msg = open_app(app)
    if ok:
        rprint(f"[green]{msg}[/green]")
    else:
        rprint(f"[red]{msg}[/red]")


def _cmd_read(path: str):
    if not path:
        rprint("[yellow]Uso: /read <ruta>[/yellow]")
        return
    from core.tools import read_file
    ok, content = read_file(path)
    if ok:
        ext = Path(path).suffix.lstrip(".") or "text"
        lang_map = {"py": "python", "js": "javascript", "sh": "bash",
                    "md": "markdown", "json": "json", "yaml": "yaml", "yml": "yaml"}
        lang = lang_map.get(ext, "text")
        console.print(Panel(
            Syntax(content[:4000], lang, theme="monokai", line_numbers=True),
            title="[cyan]" + path + "[/cyan]",
            border_style="dim"
        ))
        if len(content) > 4000:
            rprint(f"[dim]... (mostrando primeros 4000 chars de {len(content)})[/dim]")
    else:
        rprint(f"[red]{content}[/red]")


def _cmd_ls(path: str):
    from core.tools import list_directory
    ok, output = list_directory(path or ".")
    if ok:
        rprint(output)
    else:
        rprint(f"[red]{output}[/red]")


def _cmd_sysinfo():
    from core.tools import get_system_info
    console.print(Panel(get_system_info(), title="[cyan]Informacion del Sistema[/cyan]", border_style="cyan"))


# ── Cron ──────────────────────────────────────────────────────────────────────

def _cmd_cron(arg: str, cron: CronManager):
    """
    Uso:
      /cron <horario> <mensaje>               -> notificacion de texto
      /cron <horario> llm: <prompt>           -> el LLM genera el mensaje
      /cron <horario> shell: <comando>        -> ejecuta un comando del sistema

    Ejemplos:
      /cron 09:00 Buenos dias!
      /cron */1h llm: Genera un consejo de productividad aleatorio
      /cron 08:00 shell: ~/scripts/backup.sh
    """
    if not arg:
        rprint("[yellow]Uso: /cron <horario> <accion>[/yellow]")
        rprint("  Tipos de accion:")
        rprint("    /cron 09:00 Texto fijo de notificacion")
        rprint("    /cron */1h llm: Genera un consejo motivacional")
        rprint("    /cron 08:00 shell: ~/scripts/backup.sh")
        return
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        rprint("[yellow]Faltan argumentos. Uso: /cron <horario> <accion>[/yellow]")
        return

    schedule, action = parts
    from core.cron_manager import JOB_NOTIFY, JOB_LLM, JOB_SHELL

    if action.lower().startswith("llm:"):
        job_type = JOB_LLM
        action = action[4:].strip()
        type_label = "LLM"
    elif action.lower().startswith("shell:"):
        job_type = JOB_SHELL
        action = action[6:].strip()
        type_label = "Shell"
    else:
        job_type = JOB_NOTIFY
        type_label = "Notificacion"

    # Para tareas llm, pasar la sesion activa para guardar en el historial
    sid = state.get('session_id') if job_type == JOB_LLM else None
    job_id = cron.add_job(schedule, action, job_type=job_type, session_id=sid)
    if job_id:
        rprint(f"[green]Tarea programada[/green] (ID: {job_id}) [{type_label}]: '{action}' -> {schedule}")
    else:
        rprint("[red]Formato de horario invalido.[/red] Usa HH:MM, */Nm o */Nh")


def _cmd_cron_list(cron: CronManager):
    jobs = cron.list_jobs()
    if not jobs:
        rprint("[yellow]No hay tareas programadas.[/yellow]")
        return
    type_icons = {"notify": "🔔", "llm": "🤖", "shell": "⚙️"}
    table = Table(title="Tareas Programadas", show_lines=True)
    table.add_column("ID", style="cyan", width=5)
    table.add_column("Tipo", style="magenta", width=10)
    table.add_column("Horario", style="green", width=10)
    table.add_column("Accion", style="white")
    table.add_column("Proxima", style="yellow", width=17)
    for j in jobs:
        jtype = j.get("type", "notify")
        icon = type_icons.get(jtype, "🔔")
        table.add_row(str(j["id"]), icon + " " + jtype, j["schedule"], j["action"], j.get("next_run", "-")[:16])
    console.print(table)


def _cmd_cron_del(arg: str, cron: CronManager):
    if not arg:
        rprint("[yellow]Uso: /cron-del <id>[/yellow]")
        return
    try:
        job_id = int(arg)
        ok = cron.remove_job(job_id)
        if ok:
            rprint(f"[green]Tarea {job_id} eliminada.[/green]")
        else:
            rprint(f"[red]No se encontro tarea con ID {job_id}.[/red]")
    except ValueError:
        rprint("[red]El ID debe ser un numero.[/red]")


# ── Historial ─────────────────────────────────────────────────────────────────

def _cmd_sessions():
    sessions = database.list_sessions(10)
    if not sessions:
        rprint("[yellow]No hay sesiones previas.[/yellow]")
        return
    table = Table(title="Ultimas Sesiones", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Fecha", style="green")
    table.add_column("Modelo", style="yellow")
    table.add_column("Msgs", style="white", width=5)
    table.add_column("Resumen", style="dim")
    for s in sessions:
        label = s.get("label") or ""
        if label.startswith("summary:"):
            summary = label[8:60] + ("..." if len(label) > 68 else "")
        else:
            summary = "-"
        table.add_row(
            str(s["id"]),
            s["created_at"][:19],
            s["model"] or "-",
            str(s["total_messages"] or 0),
            summary,
        )
    console.print(table)



def _cmd_sessions_del(arg: str, state: dict):
    """Borra una sesion concreta por ID. No permite borrar la sesion activa."""
    if not arg:
        rprint("[yellow]Uso: /sessions-del <id>[/yellow]")
        return
    try:
        session_id = int(arg)
    except ValueError:
        rprint("[red]El ID debe ser un numero.[/red]")
        return
    if session_id == state.get("session_id"):
        rprint("[red]No puedes borrar la sesion activa.[/red] Usa /reset primero para abrir una nueva.")
        return
    ok = database.delete_session(session_id)
    if ok:
        rprint(f"[green]Sesion {session_id} eliminada.[/green]")
    else:
        rprint(f"[red]No se encontro la sesion {session_id}.[/red]")


def _cmd_sessions_clear(state: dict):
    """Borra todas las sesiones excepto la activa."""
    current = state.get("session_id")
    try:
        answer = input("  Borrar todas las sesiones excepto la actual? [s/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        rprint("[yellow]Cancelado.[/yellow]")
        return
    if answer not in ("s", "si", "y", "yes"):
        rprint("[yellow]Cancelado.[/yellow]")
        return
    count = database.delete_all_sessions_except(current)
    rprint(f"[green]{count} sesion(es) eliminadas.[/green] La sesion actual ({current}) se ha conservado.")


# ── Ayuda ─────────────────────────────────────────────────────────────────────

def _cmd_help():
    table = Table(title="Comandos Disponibles", show_lines=True)
    table.add_column("Comando", style="cyan bold")
    table.add_column("Descripcion", style="white")
    cmds = [
        ("── Modelo ──", ""),
        ("/list", "Lista los modelos en el backend activo"),
        ("/load <model>", "Carga un modelo"),
        ("/unload [model]", "Descarga el modelo activo (o el indicado)"),
        ("/status", "Estado y estadisticas"),
        ("/reset", "Resetea el contexto (nueva sesion)"),
        ("── Memoria y contexto ──", ""),
        ("/memory <texto>", "Guarda en MEMORY.md"),
        ("/compact", "Resume y compacta el contexto -> MEMORY.md"),
        ("/search <texto>", "Busca en todo el historial"),
        ("── SOULs (personalidades) ──", ""),
        ("/souls", "Lista los SOULs disponibles"),
        ("/soul <nombre>", "Cambia de personalidad (souls/<nombre>.md)"),
        ("/soul", "Vuelve al SOUL.md por defecto"),
        ("── Herramientas del sistema ──", ""),
        ("/run <cmd>", "Ejecuta un comando de shell"),
        ("/open <app>", "Abre una aplicacion o fichero"),
        ("/read <ruta>", "Lee el contenido de un fichero"),
        ("/ls [ruta]", "Lista el contenido de un directorio"),
        ("/sysinfo", "Informacion del sistema"),
        ("── Cron ──", ""),
        ("/cron <horario> <texto>", "🔔 Notificacion de texto fijo"),
        ("/cron <horario> llm: <prompt>", "🤖 El LLM genera el mensaje con IA"),
        ("/cron <horario> shell: <cmd>", "⚙️  Ejecuta un comando o script"),
        ("", "Horario: HH:MM | */Nm | */Nh"),
        ("", "Ej: /cron 09:00 Buenos dias"),
        ("", "Ej: /cron */1h llm: Consejo motivacional"),
        ("", "Ej: /cron 08:00 shell: ~/backup.sh"),
        ("/cron-list", "Lista tareas (muestra tipo con icono)"),
        ("/cron-del <id>", "Elimina una tarea"),
        ("── General ──", ""),
        ("/sessions", "Ultimas sesiones con resumen"),
        ("/sessions-del <id>", "Borra una sesion por ID"),
        ("/sessions-clear", "Borra todas excepto la actual"),
        ("/help", "Esta ayuda"),
        ("/exit", "Sale del agente"),
    ]
    for cmd, desc in cmds:
        if desc == "":
            table.add_row("[bold dim]" + cmd + "[/bold dim]", "")
        else:
            table.add_row(cmd, desc)
    console.print(table)
