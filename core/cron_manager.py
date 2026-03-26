"""
cron_manager.py — Sistema de tareas programadas para el agente
Compatible con macOS y Linux.

Tipos de tarea (campo "type"):
  notify  — Notificacion de texto fijo (comportamiento original)
  llm     — El agente genera un mensaje con el LLM y lo envia
  shell   — Ejecuta un comando o script del sistema
"""

import asyncio
import threading
import time
import re
import json
import subprocess
import platform
from datetime import datetime, timedelta
from typing import Optional, List, Callable
from pathlib import Path


JOBS_FILE = Path(__file__).parent.parent / "cron_jobs.json"

# Tipos validos de tarea
JOB_NOTIFY = "notify"   # Texto fijo
JOB_LLM    = "llm"      # Generar mensaje con el LLM
JOB_SHELL  = "shell"    # Ejecutar comando del sistema


_print_lock = threading.Lock()


class CronManager:
    def __init__(self, notify_callback: Callable[[str], None] = None):
        self._jobs = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._terminal_notify = notify_callback or self._default_notify
        self._telegram_send = None
        self._loop = None
        self._llm_chat = None   # funcion chat(model, messages) -> (text, tokens)
        self._active_model = None    # modelo activo del agente
        self._save_to_context = None # callback(session_id, role, content) para guardar en BD
        self._tts_send = None         # callable(text) -> wav_path  para sintetizar
        self._tts_voice_sender = None  # async callable(chat_id, wav_path) para enviar audio
        self._running = False
        self._thread = None
        self._load_jobs()

    # ── Configuracion ─────────────────────────────────────────────────────────

    def set_telegram_send_callback(self, callback):
        self._telegram_send = callback

    def set_event_loop(self, loop):
        self._loop = loop

    def set_llm(self, chat_fn, model_getter):
        """
        Registra la funcion de chat del LLM y un getter del modelo activo.
        chat_fn: callable(model, messages) -> (text, tokens)
        model_getter: callable() -> str o None
        """
        self._llm_chat = chat_fn
        self._model_getter = model_getter

    def set_context_callback(self, callback):
        """
        Registra un callback para guardar mensajes del cron en el historial.
        callback: callable(session_id, role, content) -> None
        """
        self._save_to_context = callback

    def set_tts_callbacks(self, synthesize_fn, voice_sender_fn):
        """
        Registra los callbacks de TTS.
        synthesize_fn   : callable(text) -> wav_path  (sintetiza texto a WAV)
        voice_sender_fn : async callable(chat_id, wav_path)  (envia el WAV por Telegram)
        """
        self._tts_send = synthesize_fn
        self._tts_voice_sender = voice_sender_fn

    # ── API publica ───────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop_fn, daemon=True, name="cron-worker")
        self._thread.start()

    def stop(self):
        self._running = False

    def add_job(self, schedule: str, action: str,
                job_type: str = JOB_NOTIFY,
                telegram_chat_id: int = None,
                session_id: int = None) -> Optional[int]:
        """
        Añade un trabajo.
        schedule   : HH:MM | */Nm | */Nh
        action     : texto, prompt LLM o comando shell segun job_type
        job_type   : "notify" | "llm" | "shell"
        session_id : sesion donde guardar el mensaje generado (para llm)
        Devuelve el ID o None si el formato de schedule es invalido.
        """
        if job_type not in (JOB_NOTIFY, JOB_LLM, JOB_SHELL):
            job_type = JOB_NOTIFY
        next_run = self._calc_next_run(schedule)
        if next_run is None:
            return None
        with self._lock:
            job_id = self._next_id
            self._next_id += 1
            self._jobs[job_id] = {
                "id": job_id,
                "schedule": schedule,
                "action": action,
                "type": job_type,
                "next_run": next_run.isoformat(),
                "created_at": datetime.now().isoformat(),
                "telegram_chat_id": telegram_chat_id,
                "session_id": session_id,
            }
        self._save_jobs()
        return job_id

    def remove_job(self, job_id: int) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._save_jobs()
                return True
        return False

    def clear_all(self):
        """Borra todas las tareas y elimina cron_jobs.json."""
        with self._lock:
            self._jobs = {}
            self._next_id = 1
        if JOBS_FILE.exists():
            JOBS_FILE.unlink()

    def list_jobs(self) -> List[dict]:
        with self._lock:
            return list(self._jobs.values())

    # ── Bucle interno ─────────────────────────────────────────────────────────

    def _loop_fn(self):
        while self._running:
            now = datetime.now()
            fired = []
            with self._lock:
                for job_id, job in self._jobs.items():
                    next_run = datetime.fromisoformat(job["next_run"])
                    if now >= next_run:
                        fired.append(dict(job))
                        new_next = self._calc_next_run(job["schedule"])
                        if new_next:
                            job["next_run"] = new_next.isoformat()
            if fired:
                self._save_jobs()
                for job in fired:
                    self._execute_job(job)
            time.sleep(10)

    def _execute_job(self, job: dict):
        job_type = job.get("type", JOB_NOTIFY)
        timestamp = datetime.now().strftime("%H:%M")

        if job_type == JOB_SHELL:
            self._execute_shell(job, timestamp)
        elif job_type == JOB_LLM:
            self._execute_llm(job, timestamp)
        else:
            self._execute_notify(job, timestamp)

    # ── Tipo: notify ──────────────────────────────────────────────────────────

    def _execute_notify(self, job: dict, timestamp: str):
        action = job["action"]
        self._system_notify("Recordatorio (" + timestamp + ")", action)
        self._terminal_notify("🔔 Enviando recordatorio de las " + timestamp)
        self._send_telegram(job, action)

    # ── Tipo: shell ───────────────────────────────────────────────────────────

    def _execute_shell(self, job: dict, timestamp: str):
        cmd = job["action"]
        self._terminal_notify("⚙️ Ejecutando tarea shell de las " + timestamp)
        try:
            # Seguridad: aplicar los mismos filtros que run_shell
            from core.tools import is_blocked
            blocked, pattern = is_blocked(cmd)
            if blocked:
                result = "Bloqueado por seguridad: " + pattern
                self._terminal_notify("[cron] " + result)
                self._send_telegram(job, "❌ Cron bloqueado: " + result)
                return

            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            output = (proc.stdout or "").strip() or "(sin salida)"
            if proc.stderr:
                output += "\nSTDERR: " + proc.stderr.strip()
            if len(output) > 500:
                output = output[:500] + "..."

            status = "OK" if proc.returncode == 0 else "Error (codigo " + str(proc.returncode) + ")"
            summary = "[cron " + timestamp + "] " + status + "\n$ " + cmd + "\n" + output
            self._terminal_notify("⚙️ Tarea shell de las " + timestamp + ": " + status)
            self._send_telegram(job, output)

        except subprocess.TimeoutExpired:
            msg = "[cron] Timeout ejecutando: " + cmd
            self._terminal_notify(msg)
            self._send_telegram(job, "Timeout ejecutando el comando.")
        except Exception as e:
            msg = "[cron] Error: " + str(e)
            self._terminal_notify(msg)
            self._send_telegram(job, "Error ejecutando el comando.")

    # ── Tipo: llm ─────────────────────────────────────────────────────────────

    def _execute_llm(self, job: dict, timestamp: str):
        # Verificar que el LLM esta registrado
        if not self._llm_chat:
            msg = "[cron] ERROR: LLM no registrado. El cron llm: requiere que el agente este activo con un modelo cargado."
            self._terminal_notify(msg)
            self._send_telegram(job, "Error ejecutando el comando.")
            return

        # Obtener modelo activo
        model = None
        if hasattr(self, "_model_getter") and self._model_getter:
            try:
                model = self._model_getter()
            except Exception:
                pass
        if not model:
            msg = "[cron] Sin modelo activo. Carga un modelo con /load antes de usar cron llm:"
            self._terminal_notify(msg)
            self._send_telegram(job, "Error ejecutando el comando.")
            return

        prompt = job["action"]
        self._terminal_notify("🤖 Enviando recordatorio LLM de las " + timestamp)

        try:
            full_prompt = (
                "Fecha y hora actual: " + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n"
                + prompt
            )
            text, _, _files = self._llm_chat(
                model=model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.8,
                max_tokens=512,
            )
            text = text.strip()
            message = text

            # Guardar en el historial para dar continuidad al chat
            session_id = job.get("session_id")
            if self._save_to_context and session_id:
                try:
                    # Guardamos el prompt como "user" y la respuesta como "assistant"
                    self._save_to_context(session_id, "user", "[cron] " + prompt)
                    self._save_to_context(session_id, "assistant", text)
                except Exception as e:
                    print("[cron] Error guardando en contexto: " + str(e), flush=True)

            # Mostrar en terminal solo si TTS no esta activo
            try:
                from core import tts_engine as _tts
                tts_active = _tts.is_enabled()
            except Exception:
                tts_active = False
            if not tts_active:
                with _print_lock:
                    self._terminal_notify("🤖 Recordatorio LLM de las " + timestamp + " enviado.")
            self._send_telegram(job, message)

        except Exception as e:
            msg = "[cron] Error LLM: " + str(e)
            self._terminal_notify(msg)
            self._send_telegram(job, "Error ejecutando el comando.")

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _send_telegram(self, job: dict, message: str):
        """
        Envia mensaje al chat de Telegram.
        Si TTS esta activo (_tts_send registrado), sintetiza y envia audio.
        Sino envia texto plano.
        """
        chat_id = job.get("telegram_chat_id")
        if not chat_id or not self._loop:
            return
        try:
            if self._tts_send:
                # Sintetizar en el hilo del cron y enviar audio
                asyncio.run_coroutine_threadsafe(
                    self._send_voice_cron(chat_id, message), self._loop
                )
            elif self._telegram_send:
                asyncio.run_coroutine_threadsafe(
                    self._telegram_send(chat_id, message), self._loop
                )
        except Exception as e:
            print("[cron] Error Telegram: " + str(e), flush=True)

    async def _send_voice_cron(self, chat_id: int, message: str):
        """Sintetiza el mensaje con TTS y lo envia como nota de voz."""
        import asyncio as _asyncio
        from pathlib import Path
        try:
            loop = _asyncio.get_event_loop()
            # _tts_send es un callable(text) -> wav_path  que corre en executor
            wav_path = await loop.run_in_executor(None, self._tts_send, message)
            if wav_path and Path(wav_path).exists():
                await self._tts_voice_sender(chat_id, wav_path)
                Path(wav_path).unlink(missing_ok=True)
                # Confirmacion en terminal
                timestamp = datetime.now().strftime("%H:%M")
                self._default_notify("\U0001f50a Recordatorio de voz de las " + timestamp + " enviado.")
            else:
                # Fallback a texto si TTS falla
                if self._telegram_send:
                    await self._telegram_send(chat_id, message)
        except Exception as e:
            print("[cron] Error voz: " + str(e), flush=True)
            if self._telegram_send:
                await self._telegram_send(chat_id, message)

    def _system_notify(self, title: str, message: str):
        """Envia notificacion del sistema en un subproceso no bloqueante."""
        system = platform.system()
        try:
            if system == "Darwin":
                script = 'display notification "' + message + '" with title "' + title + '" sound name "Ping"'
                # Popen en lugar de run para no bloquear el hilo del cron
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Linux":
                subprocess.Popen(
                    ["notify-send", title, message, "--urgency=normal"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def _calc_next_run(self, schedule: str) -> Optional[datetime]:
        import random
        now = datetime.now()

        # HH:MM — diario a hora fija
        if re.fullmatch(r"\d{1,2}:\d{2}", schedule):
            try:
                h, m = map(int, schedule.split(":"))
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target
            except ValueError:
                return None

        # HH:MM-HH:MM — diario a hora aleatoria dentro del rango
        m_range = re.fullmatch(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", schedule)
        if m_range:
            try:
                h1, m1 = map(int, m_range.group(1).split(":"))
                h2, m2 = map(int, m_range.group(2).split(":"))
                start_min = h1 * 60 + m1
                end_min   = h2 * 60 + m2
                if end_min <= start_min:
                    return None
                rand_min = random.randint(start_min, end_min)
                target = now.replace(hour=rand_min // 60, minute=rand_min % 60,
                                     second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target
            except ValueError:
                return None

        # */Nm — cada N minutos
        m_min = re.fullmatch(r"\*/(\d+)m", schedule)
        if m_min:
            return now + timedelta(minutes=int(m_min.group(1)))

        # */Nh — cada N horas
        m_hr = re.fullmatch(r"\*/(\d+)h", schedule)
        if m_hr:
            return now + timedelta(hours=int(m_hr.group(1)))

        return None

    def _save_jobs(self):
        try:
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump({"next_id": self._next_id, "jobs": self._jobs}, f, indent=2, default=str)
        except Exception as e:
            print("[cron] Error guardando: " + str(e), flush=True)

    def _load_jobs(self):
        if JOBS_FILE.exists():
            try:
                data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
                self._next_id = data.get("next_id", 1)
                self._jobs = {int(k): v for k, v in data.get("jobs", {}).items()}
            except Exception:
                pass

    @staticmethod
    def _default_notify(message: str):
        with _print_lock:
            print("\n" + message, flush=True)
            print("\n\033[1;32mTú\033[0m: ", end="", flush=True)
