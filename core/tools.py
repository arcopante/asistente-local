"""
tools.py — Herramientas del sistema que el agente puede ejecutar
El agente detecta intención de ejecutar acciones y las propone al usuario.
"""

import os
import re
import subprocess
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich import print as rprint

console = Console()

# ── Seguridad: comandos BLOQUEADOS (nunca se ejecutan) ───────────────────────
# Estos comandos están prohibidos siempre, sin posibilidad de confirmación.
BLOCKED_PATTERNS = [
    # Borrado de ficheros y directorios
    r"\brm\b",                        # rm (cualquier variante)
    r"\brmdir\b",                     # rmdir
    r"\bsrm\b",                       # srm (borrado seguro)
    r"\bshred\b",                     # shred

    # Escalada de privilegios
    r"\bsudo\b",                      # sudo
    r"\bsu\s",                        # su <usuario>
    r"\bdoas\b",                      # doas (alternativa a sudo en BSD)
    r"\bpkexec\b",                    # pkexec (escalada en Linux)

    # Movimiento y sobreescritura de ficheros
    r"\bmv\b",                        # mv (mover/renombrar)
    r"\bcp\s+.*-.*f\b",             # cp con -f (forzar sobreescritura)

    # Formateo y escritura en dispositivos
    r"\bmkfs\b",                      # mkfs (formatear particion)
    r"\bdd\b",                        # dd (escritura directa a dispositivo)
    r"\bdiskutil\s+erase\b",        # diskutil erase (macOS)
    r"\bdiskutil\s+format\b",       # diskutil format (macOS)

    # Apagado y reinicio del sistema
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binit\s+[0-6]\b",            # init 0/6 (apagado en Linux)
    r"\bsystemctl\s+(poweroff|reboot|halt)\b",

    # Ejecución remota de scripts (piping hacia shell)
    r"\bcurl\s+.*\|\s*(bash|sh|zsh|fish)\b",
    r"\bwget\s+.*\|\s*(bash|sh|zsh|fish)\b",
    r"\bfetch\s+.*\|\s*(bash|sh|zsh|fish)\b",

    # Manipulacion del historial y entorno
    r"\bchmod\s+(777|a\+[rwx])\b", # chmod permisivo
    r"\bchown\b",                     # cambiar propietario
    r"\bchflags\b",                   # chflags (macOS)

    # Procesos
    r"\bkillall\b",                   # killall
    r"\bpkill\b",                     # pkill

    # Inyeccion y escapes
    r";\s*(rm|sudo|mv|dd|mkfs|shutdown|reboot)\b",  # encadenado con ;
    r"&&\s*(rm|sudo|mv|dd|mkfs|shutdown|reboot)\b", # encadenado con &&
    r"\|\s*(rm|sudo|mv|dd|mkfs|shutdown|reboot)\b",# encadenado con |

    # Ficheros de sistema criticos
    r">\s*/etc/",                       # sobreescribir /etc/
    r">\s*/boot/",                      # sobreescribir /boot/
    r">\s*/System/",                    # sobreescribir /System/ (macOS)
    r">\s*/dev/",                       # escribir a dispositivo
]

# ── Seguridad: comandos que REQUIEREN CONFIRMACION ────────────────────────────
# Se pueden ejecutar en terminal si el usuario confirma. Bloqueados en Telegram.
CONFIRM_PATTERNS = [
    r"\bkill\s+-9\b",               # kill -9 (forzar fin de proceso)
    r"\bkill\b",                      # kill (fin de proceso)
    r"\bnohup\b",                     # nohup (ejecutar en segundo plano)
    r"\bat\b",                        # at (programar ejecucion)
    r"\bcrontab\b",                   # crontab (modificar cron del sistema)
    r"\blaunchctl\b",                 # launchctl (servicios macOS)
    r"\bsystemctl\b",                 # systemctl (servicios Linux)
    r"\bservice\b",                   # service (servicios Linux)
    r"\bnpm\s+install\s+-g\b",     # npm install global
    r"\bpip\s+install\b",           # pip install
    r"\bbrew\s+install\b",          # brew install
    r"\bapt(-get)?\s+install\b",    # apt install
    r"\bopen\s+-a\b",               # open -a (abrir app macOS)
    r"\bscreen\b",                    # screen (sesion persistente)
    r"\btmux\b",                      # tmux (sesion persistente)
]

# Aplicaciones conocidas por plataforma
APPS_MAC = {
    "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
    "terminal": "Terminal", "finder": "Finder", "notas": "Notes",
    "notes": "Notes", "calendario": "Calendar", "calendar": "Calendar",
    "musica": "Music", "music": "Music", "spotify": "Spotify",
    "vscode": "Visual Studio Code", "code": "Visual Studio Code",
    "lmstudio": "LM Studio",
}


def is_blocked(cmd: str) -> Tuple[bool, str]:
    """
    Comprueba si un comando contiene patrones BLOQUEADOS.
    Devuelve (bloqueado, patron_encontrado).
    Estos comandos nunca se ejecutan, ni con confirmacion.
    """
    cmd_lower = cmd.lower()
    for pattern in BLOCKED_PATTERNS:
        m = re.search(pattern, cmd_lower)
        if m:
            return True, m.group(0)
    return False, ""


def needs_confirm(cmd: str) -> bool:
    """Comprueba si un comando requiere confirmacion antes de ejecutar."""
    cmd_lower = cmd.lower()
    return any(re.search(p, cmd_lower) for p in CONFIRM_PATTERNS)


def is_dangerous(cmd: str) -> bool:
    """Compatibilidad: devuelve True si el comando esta bloqueado o requiere confirmacion."""
    blocked, _ = is_blocked(cmd)
    return blocked or needs_confirm(cmd)


def confirm_execution(cmd: str) -> bool:
    """Pide confirmacion al usuario antes de ejecutar (solo terminal)."""
    console.print(Panel(
        "[bold yellow]Comando que requiere confirmacion:[/bold yellow]\n[white]" + cmd + "[/white]",
        title="Confirmacion requerida",
        border_style="yellow"
    ))
    try:
        answer = input("  Ejecutar? [s/N]: ").strip().lower()
        return answer in ("s", "si", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def run_shell(cmd: str, require_confirm: bool = False) -> Tuple[int, str, str]:
    """
    Ejecuta un comando de shell con verificacion de seguridad en dos niveles:
      1. BLOQUEADO  -> rechazado siempre, sin confirmacion posible.
      2. CONFIRMACION -> solo se ejecuta si el usuario confirma (solo en terminal).
    Devuelve (returncode, stdout, stderr).
    """
    # Nivel 1: bloqueo absoluto
    blocked, pattern = is_blocked(cmd)
    if blocked:
        return -1, "", (
            "Comando bloqueado por seguridad (patron: " + pattern + ").\n"
            "Los comandos rm, mv, sudo y otros destructivos estan prohibidos."
        )

    # Nivel 2: requiere confirmacion
    if needs_confirm(cmd):
        require_confirm = True

    if require_confirm and not confirm_execution(cmd):
        return -1, "", "Ejecucion cancelada por el usuario."

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
            env={**os.environ, "TERM": "xterm-256color"}
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Tiempo de espera agotado (30s)."
    except Exception as e:
        return -1, "", str(e)


def format_shell_result(cmd: str, returncode: int, stdout: str, stderr: str) -> str:
    """Formatea el resultado de un comando para mostrarlo en el terminal."""
    lines = []
    lines.append(f"\n[dim]$ {cmd}[/dim]")

    if returncode == -1 and "cancelada" in stderr:
        lines.append(f"[yellow]{stderr}[/yellow]")
        return "\n".join(lines)

    if stdout.strip():
        # Mostrar con syntax highlight si parece código
        console.print("\n".join(lines))
        console.print(Syntax(stdout.rstrip(), "bash", theme="monokai", line_numbers=False))
        lines = []

    if stderr.strip():
        lines.append(f"[red]{stderr.strip()}[/red]")

    status = "[green]✓ OK[/green]" if returncode == 0 else f"[red]✗ Error (código {returncode})[/red]"
    lines.append(status)
    return "\n".join(lines)


def open_app(app_name: str) -> Tuple[bool, str]:
    """Abre una aplicación en macOS o Linux."""
    system = platform.system()
    name_lower = app_name.lower().strip()

    if system == "Darwin":
        # Intentar con nombre amigable primero
        real_name = APPS_MAC.get(name_lower, app_name)
        code, out, err = run_shell(f'open -a "{real_name}"')
        if code == 0:
            return True, f"Abriendo {real_name}..."
        # Fallback: abrir como URL o fichero
        code, out, err = run_shell(f'open "{app_name}"')
        return code == 0, out or err

    elif system == "Linux":
        # Intentar xdg-open, entonces buscar en PATH
        if shutil.which(name_lower):
            subprocess.Popen([name_lower], start_new_session=True)
            return True, f"Lanzando {app_name}..."
        code, out, err = run_shell(f'xdg-open "{app_name}" &')
        return code == 0, out or err

    return False, f"Sistema no soportado: {system}"


def read_file(path: str) -> Tuple[bool, str]:
    """Lee el contenido de un fichero."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return False, f"El fichero no existe: {path}"
        if p.stat().st_size > 1024 * 1024:  # > 1MB
            return False, "Fichero demasiado grande (máx. 1MB)."
        content = p.read_text(encoding="utf-8", errors="replace")
        return True, content
    except Exception as e:
        return False, str(e)


def write_file(path: str, content: str, append: bool = False) -> Tuple[bool, str]:
    """Escribe o añade contenido a un fichero."""
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Añadido a" if append else "Escrito en"
        return True, f"{action} {p}"
    except Exception as e:
        return False, str(e)


def list_directory(path: str = ".") -> Tuple[bool, str]:
    """Lista el contenido de un directorio."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return False, f"No existe: {path}"
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"📁 {p}\n"]
        for item in items[:50]:  # máximo 50 entradas
            icon = "📁" if item.is_dir() else "📄"
            size = ""
            if item.is_file():
                s = item.stat().st_size
                size = f"  [{_human_size(s)}]"
            lines.append(f"  {icon} {item.name}{size}")
        if len(list(p.iterdir())) > 50:
            lines.append("  ... (más ficheros)")
        return True, "\n".join(lines)
    except Exception as e:
        return False, str(e)


def get_system_info() -> str:
    """Devuelve información del sistema."""
    system = platform.system()
    info = {
        "OS": f"{system} {platform.release()}",
        "Máquina": platform.machine(),
        "Python": platform.python_version(),
        "Directorio actual": str(Path.cwd()),
        "Usuario": os.environ.get("USER", os.environ.get("USERNAME", "-")),
        "Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return "\n".join(f"  {k}: {v}" for k, v in info.items())


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size //= 1024
    return f"{size:.0f}TB"


# ── Detección de intención de herramienta en texto libre ─────────────────────

TOOL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"ejecuta[r]?\s+(?:el\s+)?comando[:\s]+(.+)", re.I), "shell"),
    (re.compile(r"(?:corre|run|ejecuta)\s+`([^`]+)`", re.I), "shell"),
    (re.compile(r"abre?\s+(?:la\s+app\s+)?(.+)", re.I), "open"),
    (re.compile(r"lee?\s+(?:el\s+fichero\s+|el\s+archivo\s+)?(.+)", re.I), "read"),
    (re.compile(r"lista[r]?\s+(?:el\s+directorio\s+|la\s+carpeta\s+)?(.+)", re.I), "ls"),
]


def detect_tool_intent(text: str) -> Optional[Tuple[str, str]]:
    """
    Intenta detectar si el texto es una solicitud de herramienta.
    Devuelve (tipo, argumento) o None.
    """
    for pattern, tool_type in TOOL_PATTERNS:
        m = pattern.search(text)
        if m:
            return tool_type, m.group(1).strip()
    return None
