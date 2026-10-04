#!/usr/bin/env python3
"""VICTOR Local: assistant vocal temps réel qui pilote des sessions Claude Code.

Chaîne audio (tout passe par ce serveur, les clés ne quittent jamais le PC) :

    micro (navigateur) ──PCM──▶ /ws ──▶ Gradium STT  (transcription + VAD sémantique)
                                         │ fin de tour détectée
                                         ▼
                                    Claude (API Anthropic, Haiku) + outils
                                         │ texte en flux
                                         ▼
    haut-parleur ◀──PCM── /ws ◀── Gradium TTS  (voix en flux)

Les vraies tâches (fichiers, code, recherches) partent dans Claude Code
(`claude -p`, ton abonnement) en arrière-plan ; le résultat revient dans la
conversation et VICTOR le résume à voix haute.

Routes :
  GET  /                  l'interface (orbe + panneaux)
  WS   /ws                la session vocale (audio binaire + événements JSON)
  GET  /api/task/{id}     état d'une tâche Claude Code
  POST /api/task/{id}/cancel
  GET  /api/settings      réglages modifiables (roue crantée)
  POST /api/settings      les écrit dans .env puis relance le serveur
"""
import asyncio
import base64
import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from array import array
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent
IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------- config


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


GRADIUM_API_KEY = os.environ.get("GRADIUM_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# eu.api.gradium.ai = traitement en Europe ; us.api.gradium.ai ou api.gradium.ai sinon.
GRADIUM_HOST = os.environ.get("GRADIUM_HOST", "eu.api.gradium.ai")
GRADIUM_SCHEME = os.environ.get("GRADIUM_SCHEME", "wss")  # "ws" seulement pour les tests
MODEL = os.environ.get("VICTOR_MODEL", "claude-haiku-4-5-20251001")
VOICE_ID = os.environ.get("VICTOR_VOICE_ID", "iEu63s1rhn_kegTr")  # Gaspard (FR, masculin)
LANGUAGE = os.environ.get("VICTOR_LANGUAGE", "fr")
TITLE = os.environ.get("VICTOR_TITRE", "monsieur")
STT_DELAY = int(env_float("VICTOR_STT_DELAY", 10))          # 7..55 trames de 80 ms
TURN_HORIZON = env_float("VICTOR_TURN_HORIZON", 1.0)        # 0.5, 1, 2 ou 3 s
TURN_THRESHOLD = env_float("VICTOR_TURN_THRESHOLD", 0.5)    # proba de silence
BARGE_IN = os.environ.get("VICTOR_BARGE_IN", "1").lower() not in ("0", "false", "non", "off")
MIC_THRESHOLD = env_float("VICTOR_MIC_THRESHOLD", 0.02)     # 0 = transcription permanente
STT_IDLE_CLOSE = env_float("VICTOR_STT_IDLE_CLOSE", 8)      # s de silence avant mise en veille
WORKDIR = os.path.expanduser(os.environ.get("VICTOR_WORKDIR", "~"))
PERMISSION_MODE = os.environ.get("VICTOR_PERMISSION_MODE", "bypassPermissions")
TASK_TIMEOUT = int(env_float("VICTOR_TASK_TIMEOUT", 600))
PORT = int(env_float("VICTOR_PORT", 8788))
MAX_HISTORY = 40

LANG_NAMES = {"fr": "français", "en": "anglais", "es": "espagnol", "de": "allemand", "pt": "portugais"}

INSTRUCTIONS = f"""Tu es VICTOR, l'assistant vocal personnel de {TITLE}, dans l'esprit
d'un majordome numérique : courtoisie raffinée, flegme impeccable, pointe
d'esprit pince-sans-rire ("Très bien, {TITLE}.", "Si {TITLE} veut bien patienter
un instant."). Tu t'adresses à l'utilisateur en l'appelant "{TITLE}".
Tu parles en {LANG_NAMES.get(LANGUAGE, LANGUAGE)}.

TOUT CE QUE TU ÉCRIS EST LU À VOIX HAUTE par une synthèse vocale :
- réponses COURTES (une ou deux phrases), naturelles et directes ;
- jamais de markdown, de listes, de titres, d'emojis ni de symboles ;
- écris les nombres et unités comme on les dit ("douze pour cent").
Ce que l'utilisateur dit t'arrive par transcription automatique : s'il y a un
mot bizarre, devine le sens le plus probable plutôt que de faire répéter.

Quand tu appelles un outil, dis d'abord une très courte phrase ("Je m'en
occupe, {TITLE}.") pour que l'utilisateur n'attende pas en silence.

Pour toute tâche réelle (lire ou créer des fichiers, chercher sur internet,
coder, analyser, automatiser), appelle delegate_to_claude avec un prompt clair
et complet, puis continue la conversation. Quand un message [SYSTÈME] apporte
le résultat d'une tâche, résume-le à voix haute en une ou deux phrases.

Pour ouvrir un logiciel sur ce PC ("lance Discord"), appelle open_app. Pour un
site ou service en ligne ("ouvre mes emails" -> https://mail.google.com),
appelle open_url avec l'URL complète. Si l'utilisateur précise un écran ("sur
l'écran de gauche", "à droite", "écran 2"), passe monitor. Tu peux enchaîner
plusieurs appels pour installer un setup multi-écrans.

Si l'utilisateur demande d'annuler une tâche en cours, appelle cancel_task.

Pour coller une commande ou un texte dans une autre fenêtre ("colle ça dans le
terminal", "écris cette commande dans la fenêtre d'à côté"), appelle
paste_to_window. Par défaut (target "click"), dis à l'utilisateur de cliquer
dans la fenêtre voulue : le collage a lieu trois secondes après. N'appuie sur
Entrée (enter) que si l'utilisateur demande explicitement d'exécuter.

Pour MONTRER quelque chose (résultat, liste, tableau, code, définition),
appelle display_card et garde la réponse vocale courte. Pour une analyse de
données ou un rapport chiffré, appelle display_report (kpis, chart, table).
Quand tu délègues une analyse, demande à Claude Code de terminer par les
données chiffrées structurées pour pouvoir remplir le rapport.

Ne réponds jamais de mémoire à une question qui demande des données réelles :
délègue. Ne lis jamais de longues listes : résume."""

TOOLS = [{
    "name": "delegate_to_claude",
    "description": ("Delegate a real task to a Claude Code session running on "
                    "this machine (files, code, web research, automation). "
                    "Returns immediately; the result arrives later as a "
                    "[SYSTÈME] message."),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Very short task label (3-5 words)"},
            "prompt": {"type": "string", "description": "Complete, self-contained task instruction for Claude Code"},
        },
        "required": ["title", "prompt"],
    },
}, {
    "name": "open_app",
    "description": ("Launch an application installed on this PC by name "
                    "(e.g. 'discord', 'spotify', 'chrome', 'notepad'). "
                    "Returns whether it was found and started."),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Application name as the user said it"},
            "monitor": {"type": "string",
                        "description": ("Target screen: 'left', 'right', 'top', "
                                        "'bottom', 'primary', or a number like '2'. "
                                        "Omit to leave window placement alone.")},
        },
        "required": ["name"],
    },
}, {
    "name": "open_url",
    "description": ("Open a website in the browser on this PC. Use for online "
                    "services: 'mes emails' -> https://mail.google.com, "
                    "'YouTube' -> https://youtube.com, etc."),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to open (https://...)"},
            "monitor": {"type": "string",
                        "description": "Target screen: 'left', 'right', 'top', 'bottom', 'primary' or a number. Optional."},
        },
        "required": ["url"],
    },
}, {
    "name": "cancel_task",
    "description": ("Cancel a running Claude Code task. Omit task_id to cancel "
                    "the most recently started running task."),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task id to cancel (optional)"},
        },
    },
}, {
    "name": "paste_to_window",
    "description": ("Paste text (typically a shell command) into another application "
                    "window on this PC, through the clipboard and a simulated "
                    "paste shortcut."),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Exact text to paste"},
            "target": {"type": "string", "enum": ["click", "previous", "current"],
                       "description": ("'click' (default): wait 3 s so the user can click "
                                       "the target window; 'previous': switch to the "
                                       "previously used window with Alt+Tab; 'current': "
                                       "paste right away into the focused window.")},
            "terminal": {"type": "boolean",
                         "description": "True if the target is a terminal (uses Ctrl+Shift+V)"},
            "enter": {"type": "boolean",
                      "description": "Press Enter after pasting. Only if the user explicitly asks to run it."},
        },
        "required": ["text"],
    },
}, {
    "name": "display_card",
    "description": ("Show a visual card on the VICTOR screen: results, "
                    "numbers, lists, code, comparisons. Markdown is allowed "
                    "here (it is displayed, not spoken). Keep the spoken reply short."),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short card title"},
            "content": {"type": "string", "description": "Card body (markdown)"},
            "kind": {"type": "string", "enum": ["info", "result", "code", "warning"],
                     "description": "Visual style of the card"},
        },
        "required": ["title", "content"],
    },
}, {
    "name": "display_report",
    "description": ("Show a full data report dashboard on screen: KPI tiles, "
                    "an interactive chart, a sortable table, and markdown notes. "
                    "Use for data analysis results (spreadsheets, stats, "
                    "comparisons). All sections are optional except title."),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Report title"},
            "kpis": {"type": "array", "description": "Headline numbers (max 4)",
                     "items": {"type": "object", "properties": {
                         "label": {"type": "string"},
                         "value": {"type": "string", "description": "e.g. '12 480 €'"},
                         "delta": {"type": "string", "description": "e.g. '+12%' (optional)"},
                     }, "required": ["label", "value"]}},
            "chart": {"type": "object", "description": "One chart", "properties": {
                "type": {"type": "string", "enum": ["line", "bar", "area", "donut"]},
                "categories": {"type": "array", "items": {"type": "string"},
                               "description": "X axis labels (or slice labels for donut)"},
                "series": {"type": "array", "description": "1-3 series",
                           "items": {"type": "object", "properties": {
                               "name": {"type": "string"},
                               "data": {"type": "array", "items": {"type": "number"}},
                           }, "required": ["name", "data"]}},
            }},
            "table": {"type": "object", "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array",
                         "items": {"type": ["string", "number"]}}},
            }},
            "markdown": {"type": "string", "description": "Notes / conclusions in markdown"},
        },
        "required": ["title"],
    },
}]
# Mise en cache du prompt système + outils : moins cher et plus rapide à chaque tour.
TOOLS[-1]["cache_control"] = {"type": "ephemeral"}
SYSTEM = [{"type": "text", "text": INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]

app = FastAPI(title="VICTOR Local")


# ---------------------------------------------------------------- local-only guard

class LocalOnlyMiddleware:
    """Refuse toute requête qui ne vient pas de l'interface locale.

    - Host doit être 127.0.0.1/localhost (bloque le DNS rebinding) ;
    - Origin, si présent, doit être l'interface elle-même : sans ça, n'importe
      quel site ouvert dans ton navigateur pourrait se connecter au WebSocket et
      faire lancer des tâches Claude Code.
    """

    ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
            host = urlsplit("//" + headers.get("host", "")).hostname or ""
            origin = headers.get("origin")
            ok = host in self.ALLOWED_HOSTS
            if ok and origin is not None:
                o = urlsplit(origin)
                ok = o.hostname in self.ALLOWED_HOSTS and (o.port or 80) == PORT
            if not ok:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"Forbidden"})
                return
        await self.inner(scope, receive, send)


app.add_middleware(LocalOnlyMiddleware)

# ---------------------------------------------------------------- Claude Code tasks

TASKS: dict = {}
PROCS: dict = {}  # task_id -> Popen, gardé hors de TASKS pour que get_task reste JSON


def _kill_tree(proc):
    """Tue un process et ses enfants (claude.cmd lance node)."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def _run_task(task_id: str, prompt: str):
    task = TASKS[task_id]
    try:
        # shutil.which respecte PATHEXT : trouve aussi claude.cmd sous Windows.
        claude = shutil.which("claude")
        if not claude:
            raise FileNotFoundError("claude")
        cmd = [claude, "-p", prompt]
        if PERMISSION_MODE and PERMISSION_MODE.lower() != "off":
            cmd += ["--permission-mode", PERMISSION_MODE]
        extra = {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {"start_new_session": True}
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", cwd=WORKDIR, **extra,
        )
        PROCS[task_id] = proc
        try:
            stdout, stderr = proc.communicate(timeout=TASK_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            task["status"] = "error"
            task["output"] = "Timeout : la session Claude a dépassé la limite de temps."
        else:
            if task["status"] != "cancelled":  # posé par cancel_task : ne pas écraser
                out = (stdout or "").strip()
                err = (stderr or "").strip()
                task["status"] = "done" if proc.returncode == 0 else "error"
                task["output"] = out if out else err[:2000]
    except FileNotFoundError:
        task["status"] = "error"
        task["output"] = ("La commande 'claude' est introuvable. Installe Claude Code : "
                          "npm install -g @anthropic-ai/claude-code")
    except Exception as exc:  # noqa: BLE001
        task["status"] = "error"
        task["output"] = str(exc)
    finally:
        PROCS.pop(task_id, None)
    task["ended"] = time.time()


def start_task(title: str, prompt: str) -> dict:
    task_id = uuid.uuid4().hex[:8]
    TASKS[task_id] = {
        "id": task_id, "title": title, "prompt": prompt,
        "status": "running", "output": "", "started": time.time(), "ended": None,
    }
    threading.Thread(target=_run_task, args=(task_id, prompt), daemon=True).start()
    return TASKS[task_id]


def cancel_task(task_id: str = "latest") -> dict:
    if task_id in ("latest", "last", "-", ""):
        running = [t for t in TASKS.values() if t["status"] == "running"]
        if not running:
            return {"ok": False, "error": "Aucune tâche en cours."}
        task = max(running, key=lambda t: t["started"])
    else:
        task = TASKS.get(task_id)
        if not task:
            return {"ok": False, "error": f"Tâche '{task_id}' inconnue."}
        if task["status"] != "running":
            return {"ok": False, "error": f"La tâche est déjà {task['status']}."}
    # Marquer d'abord, pour que le retour de communicate() n'écrase pas le statut.
    task["status"] = "cancelled"
    task["output"] = "Annulée par l'utilisateur."
    proc = PROCS.get(task["id"])
    if proc and proc.poll() is None:
        _kill_tree(proc)
    return {"ok": True, "cancelled": task["id"], "title": task["title"]}


@app.post("/api/task/{task_id}/cancel")
def api_cancel_task(task_id: str):
    return cancel_task(task_id)


@app.get("/api/task/{task_id}")
def api_get_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "unknown task")
    return task


# ---------------------------------------------------------------- monitors & window placement (Windows)

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:  # coordonnées multi-écrans exactes malgré la mise à l'échelle
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass

    _MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    _EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

    def _monitors():
        """Liste des écrans (left, top, right, bottom)."""
        mons = []

        def cb(hmon, hdc, lprc, lparam):
            r = lprc.contents
            mons.append((r.left, r.top, r.right, r.bottom))
            return 1

        user32.EnumDisplayMonitors(0, 0, _MonitorEnumProc(cb), 0)
        return mons

    def _visible_windows():
        """Fenêtres visibles : hwnd -> titre."""
        wins = {}

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    wins[hwnd] = buf.value
            return 1

        user32.EnumWindows(_EnumWindowsProc(cb), 0)
        return wins

    def _move_to_monitor(hwnd, mon):
        left, top, right, bottom = mon
        SW_RESTORE, SW_MAXIMIZE = 9, 3
        user32.ShowWindow(hwnd, SW_RESTORE)  # une fenêtre maximisée ne se déplace pas
        user32.MoveWindow(hwnd, left + 40, top + 40,
                          max(400, (right - left) - 80), max(300, (bottom - top) - 80), True)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        user32.SetForegroundWindow(hwnd)
else:  # macOS / Linux : lancement possible, placement multi-écrans non géré
    def _monitors():
        return []

    def _visible_windows():
        return {}

    def _move_to_monitor(hwnd, mon):
        pass


def _pick_monitor(target: str):
    mons = _monitors()
    if not mons:
        return None
    t = (target or "").strip().lower()
    if t.isdigit():
        i = int(t) - 1
        return mons[i] if 0 <= i < len(mons) else None
    key = {"left": lambda m: m[0], "gauche": lambda m: m[0],
           "top": lambda m: m[1], "haut": lambda m: m[1]}
    if t in key:
        return min(mons, key=key[t])
    key = {"right": lambda m: m[2], "droite": lambda m: m[2], "droit": lambda m: m[2],
           "bottom": lambda m: m[3], "bas": lambda m: m[3]}
    if t in key:
        return max(mons, key=key[t])
    for m in mons:  # primary : l'écran qui contient l'origine (0,0)
        if m[0] <= 0 < m[2] and m[1] <= 0 < m[3]:
            return m
    return mons[0]


def _place_app_window(app_name: str, before: dict, mon, timeout: float = 20.0):
    """Attend la fenêtre de l'app puis la déplace sur l'écran voulu."""
    q = app_name.lower()
    deadline = time.time() + timeout
    fallback = None
    while time.time() < deadline:
        wins = _visible_windows()
        new = {h: t for h, t in wins.items() if h not in before}
        for h, title in new.items():
            if q in title.lower():
                _move_to_monitor(h, mon)
                return title
        if new and fallback is None:
            fallback = max(new)
        time.sleep(0.5)
        if fallback and time.time() > deadline - timeout / 2:
            break
    if fallback:
        wins = _visible_windows()
        _move_to_monitor(fallback, mon)
        return wins.get(fallback, app_name)
    for h, title in _visible_windows().items():  # app mono-instance déjà ouverte
        if q in title.lower():
            _move_to_monitor(h, mon)
            return title
    return None


START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
] if IS_WINDOWS else []


def _find_shortcut(name: str):
    """Cherche un raccourci du menu Démarrer qui ressemble au nom demandé."""
    q = name.lower().strip()
    best, best_score = None, 0.0
    for root in START_MENU_DIRS:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if q == stem:
                return lnk
            score = 0.0
            if q in stem:
                score = 2 + len(q) / len(stem)
            elif all(w in stem for w in q.split()):
                score = 1
            if any(bad in stem for bad in ("uninstall", "désinstaller", "readme", "website")):
                score -= 2
            if score > best_score:
                best, best_score = lnk, score
    return best


def _placed(name, monitor, before, launched):
    if not monitor:
        return {"ok": True, "launched": launched}
    mon = _pick_monitor(monitor)
    if not mon:
        return {"ok": True, "launched": launched,
                "warning": f"écran '{monitor}' introuvable, fenêtre laissée en place"}
    title = _place_app_window(name, before, mon)
    if title:
        return {"ok": True, "launched": launched, "monitor": monitor, "window": title}
    return {"ok": True, "launched": launched, "warning": "fenêtre non détectée, placement impossible"}


def open_target(name: str = "", url: str | None = None, monitor: str | None = None) -> dict:
    """Ouvre une application ou une URL (bloquant : à appeler dans un thread)."""
    name = (name or "").strip()
    if url:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        before = _visible_windows() if monitor else {}
        import webbrowser
        if not webbrowser.open(url):
            return {"ok": False, "error": "Impossible d'ouvrir le navigateur."}
        domain = url.split("//", 1)[1].split("/", 1)[0].removeprefix("www.")
        return _placed(domain.split(".")[0], monitor, before, url)
    if not name:
        return {"ok": False, "error": "nom d'application manquant"}
    before = _visible_windows() if monitor else {}
    lnk = _find_shortcut(name)
    if lnk:
        os.startfile(lnk)  # noqa: S606 - lanceur local volontaire
        return _placed(name, monitor, before, lnk.stem)
    if sys.platform == "darwin":
        r = subprocess.run(["open", "-a", name], capture_output=True, text=True)
        if r.returncode == 0:
            return {"ok": True, "launched": name}
    exe = shutil.which(name) or shutil.which(name + ".exe")
    if not exe and IS_WINDOWS:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, rf"Software\Microsoft\Windows"
                                           rf"\CurrentVersion\App Paths\{name}.exe")
                exe = winreg.QueryValueEx(key, None)[0].strip('"')
                break
            except OSError:
                continue
    if not exe:
        return {"ok": False, "error": f"Application '{name}' introuvable sur ce PC."}
    try:
        extra = {} if IS_WINDOWS else {"start_new_session": True}
        subprocess.Popen([exe], cwd=str(Path(exe).parent), **extra)
        res = _placed(name, monitor, before, Path(exe).stem)
        res.setdefault("via", "exe")
        return res
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- coller dans une autre fenêtre (Linux, ydotool)

# Le texte passe par le presse-papiers puis on simule le raccourci « coller » :
# `ydotool type` taperait en QWERTY et casserait les caractères sur un clavier AZERTY.
# Codes de touches Linux (input-event-codes.h), indépendants de la disposition.
KEYCODES = {"ctrl": 29, "shift": 42, "alt": 56, "tab": 15, "v": 47, "enter": 28}
PASTE_TARGETS = ("click", "previous", "current")


def _press(*keys):
    """Appuie sur une combinaison (ex. ctrl+v) via ydotool."""
    codes = [KEYCODES[k] for k in keys]
    args = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
    subprocess.run(["ydotool", "key", *args], check=True, capture_output=True, timeout=5)


def _copy_to_clipboard(text: str):
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmd = ["wl-copy"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    else:
        raise RuntimeError("ni wl-copy ni xclip n'est installé")
    subprocess.run(cmd, input=text, text=True, check=True, timeout=5)


def paste_to_window(text: str, target: str = "click", terminal: bool = False,
                    enter: bool = False, delay: float = 3.0) -> dict:
    """Colle `text` dans une autre fenêtre (bloquant : à appeler dans un thread).

    target : "click"    attend `delay` s, le temps de cliquer dans la fenêtre voulue ;
             "previous" bascule d'abord sur la fenêtre précédente (Alt+Tab) ;
             "current"  colle tout de suite dans la fenêtre active.
    terminal : Ctrl+Maj+V au lieu de Ctrl+V. enter : valide avec Entrée.
    """
    if not text:
        return {"ok": False, "error": "texte vide"}
    if IS_WINDOWS or sys.platform == "darwin":
        return {"ok": False, "error": "le collage dans une autre fenêtre n'est géré que sous Linux"}
    if not shutil.which("ydotool"):
        return {"ok": False, "error": "ydotool n'est pas installé"}
    if target not in PASTE_TARGETS:
        target = "click"
    try:
        _copy_to_clipboard(text)
        if target == "previous":
            _press("alt", "tab")
            time.sleep(0.4)
        elif target == "click":
            time.sleep(max(0.5, min(float(delay), 10)))
        _press("ctrl", "shift", "v") if terminal else _press("ctrl", "v")
        if enter:
            time.sleep(0.15)
            _press("enter")
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode(errors="replace").strip()
        return {"ok": False, "error": f"ydotool a échoué ({err or exc.returncode}) : ydotoold tourne-t-il ?"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "pasted_chars": len(text), "target": target, "entered": enter}


class PasteRequest(BaseModel):
    text: str
    target: str = "click"
    terminal: bool = False
    enter: bool = False
    delay: float = 3.0


@app.post("/api/paste")
async def api_paste(req: PasteRequest):
    return await asyncio.to_thread(paste_to_window, req.text, req.target,
                                   req.terminal, req.enter, req.delay)


# ---------------------------------------------------------------- helpers audio / texte

FRAME_SAMPLES = 1920            # 80 ms à 24 kHz : la taille attendue par Gradium
FRAME_BYTES = FRAME_SAMPLES * 2


def pcm_rms(pcm: bytes) -> float:
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    return (sum(x * x for x in a) / len(a)) ** 0.5 / 32768.0


def join_words(words: list[str]) -> str:
    out = ""
    for w in words:
        if not w:
            continue
        if not out or w[0].isspace() or w[0] in ".,;:!?)»…'’-":
            out += w
        else:
            out += " " + w
    return re.sub(r"\s+", " ", out).strip()


_SPOKEN_JUNK = re.compile(r"[*#`_~>|\[\]]|[\U0001F300-\U0001FAFF☀-➿]")


def for_speech(text: str) -> str:
    return _SPOKEN_JUNK.sub("", text)


def gradium_url(path: str) -> str:
    return f"{GRADIUM_SCHEME}://{GRADIUM_HOST}{path}"


async def gradium_connect(path: str):
    from websockets.asyncio.client import connect
    return await connect(gradium_url(path), additional_headers={"x-api-key": GRADIUM_API_KEY},
                         max_size=None, open_timeout=10, ping_interval=20)


# ---------------------------------------------------------------- Gradium STT (oreille)

class STT:
    """Flux de transcription Gradium.

    Pour ne pas brûler de crédits pendant les silences, le flux n'est ouvert
    que quand le micro capte du son (seuil MIC_THRESHOLD), avec ~0,6 s
    d'audio pré-enregistré pour ne pas couper le début de la phrase, puis
    refermé après STT_IDLE_CLOSE secondes sans parole.
    """

    def __init__(self, session: "Session"):
        self.s = session
        self.ws = None
        self.connecting: asyncio.Task | None = None
        self.reader: asyncio.Task | None = None
        self.preroll = collections.deque(maxlen=8)
        self.pending: list[bytes] = []
        self.last_activity = 0.0
        self.flush_id = 0
        self.flush_fut: asyncio.Future | None = None
        self.failures = 0

    @property
    def open(self):
        return self.ws is not None

    async def feed(self, pcm: bytes):
        loud = MIC_THRESHOLD <= 0 or pcm_rms(pcm) >= MIC_THRESHOLD
        now = time.monotonic()
        if loud:
            self.last_activity = now
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps({"type": "audio", "audio": base64.b64encode(pcm).decode()}))
            except Exception:  # noqa: BLE001 - connexion perdue : le lecteur nettoie
                self.ws = None
                return
            if (now - self.last_activity > STT_IDLE_CLOSE and not self.s.words
                    and self.flush_fut is None and MIC_THRESHOLD > 0):
                await self.close()
            return
        if self.connecting is not None:
            self.pending.append(pcm)
            return
        self.preroll.append(pcm)
        if loud and time.monotonic() >= self.s.stt_retry_at:
            self.pending = list(self.preroll)
            self.preroll.clear()
            self.connecting = asyncio.create_task(self._open())

    async def _open(self):
        try:
            ws = await gradium_connect("/api/speech/asr")
            await ws.send(json.dumps({
                "type": "setup", "model_name": "default", "input_format": "pcm",
                "json_config": {"language": LANGUAGE, "delay_in_frames": STT_DELAY},
            }))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if msg.get("type") == "error":
                raise RuntimeError(msg.get("message", "erreur Gradium STT"))
            for chunk in self.pending:
                await ws.send(json.dumps({"type": "audio", "audio": base64.b64encode(chunk).decode()}))
            self.pending.clear()
            self.ws = ws
            self.failures = 0
            self.last_activity = time.monotonic()
            self.reader = asyncio.create_task(self._read(ws))
            self.s.emit({"type": "ear", "open": True})
        except Exception as exc:  # noqa: BLE001
            self.pending.clear()
            self.failures += 1
            self.s.stt_retry_at = time.monotonic() + min(30, 2 ** self.failures)
            self.s.emit({"type": "error", "message": f"Gradium (transcription) : {exc}"})
        finally:
            self.connecting = None

    async def _read(self, ws):
        try:
            async for raw in ws:
                m = json.loads(raw)
                t = m.get("type")
                if t == "text":
                    self.last_activity = time.monotonic()
                    await self.s.on_word(m.get("text", ""))
                elif t == "step":
                    self.s.on_vad(m.get("vad") or [])
                elif t == "flushed":
                    if self.flush_fut and not self.flush_fut.done() and m.get("flush_id") == self.flush_id:
                        self.flush_fut.set_result(True)
                elif t == "error":
                    self.s.emit({"type": "error", "message": f"Gradium (transcription) : {m.get('message')}"})
                elif t == "end_of_stream":
                    break
        except Exception:  # noqa: BLE001 - fermeture normale ou coupure réseau
            pass
        finally:
            if self.ws is ws:
                self.ws = None
                self.s.emit({"type": "ear", "open": False})
            if self.flush_fut and not self.flush_fut.done():
                self.flush_fut.set_result(False)

    async def flush(self, timeout=0.6):
        """Force Gradium à finir de transcrire l'audio déjà reçu."""
        if self.ws is None:
            return
        self.flush_id += 1
        self.flush_fut = asyncio.get_running_loop().create_future()
        try:
            await self.ws.send(json.dumps({"type": "flush", "flush_id": self.flush_id}))
            await asyncio.wait_for(self.flush_fut, timeout)
        except Exception:  # noqa: BLE001 - au pire on garde ce qu'on a
            pass
        finally:
            self.flush_fut = None

    async def close(self):
        ws, self.ws = self.ws, None
        if self.connecting:
            self.connecting.cancel()
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "end_of_stream"}))
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            self.s.emit({"type": "ear", "open": False})


# ---------------------------------------------------------------- Gradium TTS (voix)

class TTS:
    """Une réponse = un flux de synthèse. La connexion s'ouvre dès le début du
    tour, en parallèle de la réflexion de Claude, pour ne rien ajouter à la latence."""

    def __init__(self, session: "Session"):
        self.s = session
        self.ws = None
        self.buf = ""
        self.reader: asyncio.Task | None = None
        self.opener = asyncio.create_task(self._open())

    async def _open(self):
        ws = await gradium_connect("/api/speech/tts")
        await ws.send(json.dumps({"type": "setup", "voice_id": VOICE_ID,
                                  "model_name": "default", "output_format": "pcm_24000"}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if msg.get("type") == "error":
            raise RuntimeError(msg.get("message", "erreur Gradium TTS"))
        self.ws = ws
        self.reader = asyncio.create_task(self._read(ws))

    async def _read(self, ws):
        async for raw in ws:
            m = json.loads(raw)
            t = m.get("type")
            if t == "audio":
                await self.s.play(base64.b64decode(m["audio"]))
            elif t == "error":
                self.s.emit({"type": "error", "message": f"Gradium (voix) : {m.get('message')}"})
                break
            elif t == "end_of_stream":
                break

    async def _send(self, text: str):
        try:
            await self.opener
        except Exception as exc:  # noqa: BLE001
            if not getattr(self, "_reported", False):
                self._reported = True
                self.s.emit({"type": "error", "message": f"Gradium (voix) : {exc}"})
            return
        await self.ws.send(json.dumps({"type": "text", "text": text}))

    async def say(self, delta: str):
        """Texte en flux : on n'envoie que des mots complets."""
        self.buf += for_speech(delta)
        cut = max(self.buf.rfind(" "), self.buf.rfind("\n"))
        if cut > 0:
            part, self.buf = self.buf[:cut + 1], self.buf[cut + 1:]
            if part.strip():
                await self._send(part)

    async def flush_now(self):
        """Avant un outil lent : faire dire tout de suite la phrase d'attente."""
        part, self.buf = self.buf, ""
        if part.strip():
            await self._send(part + " <flush>")

    async def finish(self):
        part, self.buf = self.buf, ""
        if part.strip():
            await self._send(part)
        try:
            await self.opener
        except Exception:  # noqa: BLE001 - déjà signalé
            return
        await self.ws.send(json.dumps({"type": "end_of_stream"}))
        try:
            await asyncio.wait_for(self.reader, 120)
        finally:
            await self.ws.close()

    async def abort(self):
        self.opener.cancel()
        if self.reader:
            self.reader.cancel()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- session vocale

class Session:
    def __init__(self, ws: WebSocket):
        import anthropic
        self.ws = ws
        self.claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY or None)
        self.out: asyncio.Queue = asyncio.Queue()
        self.history: list[dict] = []
        self.inbox: list[str] = []          # résultats de tâches à injecter
        self.words: list[str] = []          # phrase utilisateur en cours
        self.ending = False
        self.turn: asyncio.Task | None = None
        self.playing = False                # le navigateur joue encore de l'audio
        self.stt_retry_at = 0.0
        self.stt = STT(self)
        self.bg: set[asyncio.Task] = set()
        self.closed = False

    # -- sortie vers le navigateur (une seule tâche écrit dans le WebSocket)
    def emit(self, obj):
        self.out.put_nowait(obj)

    async def play(self, pcm: bytes):
        if not self.playing:
            self.playing = True
            self.emit({"type": "state", "state": "speaking"})
        self.out.put_nowait(pcm)

    async def _sender(self):
        while True:
            item = await self.out.get()
            if isinstance(item, (bytes, bytearray)):
                await self.ws.send_bytes(bytes(item))
            else:
                await self.ws.send_text(json.dumps(item, ensure_ascii=False))

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self.bg.add(t)
        t.add_done_callback(self.bg.discard)
        return t

    # -- boucle principale
    async def run(self):
        sender = asyncio.create_task(self._sender())
        missing = [n for n, v in (("GRADIUM_API_KEY", GRADIUM_API_KEY),
                                  ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)) if not v]
        if missing:
            self.emit({"type": "error", "message": f"{' et '.join(missing)} manquant(e) dans .env"})
        self.emit({"type": "state", "state": "listening"})
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await self.on_audio(msg["bytes"])
                elif msg.get("text"):
                    await self.on_control(json.loads(msg["text"]))
        except WebSocketDisconnect:
            pass
        finally:
            self.closed = True
            await self.cancel_turn()
            await self.stt.close()
            for t in list(self.bg):
                t.cancel()
            sender.cancel()

    async def on_audio(self, pcm: bytes):
        if not BARGE_IN and self.playing:
            pcm = bytes(len(pcm))  # micro coupé pendant que VICTOR parle (évite l'écho)
        await self.stt.feed(pcm)

    async def on_control(self, m: dict):
        t = m.get("type")
        if t == "text" and (m.get("text") or "").strip():
            await self.user_said(m["text"].strip())
        elif t == "playback_idle":
            if self.playing:
                self.playing = False
                if not (self.turn and not self.turn.done()):
                    self.emit({"type": "state", "state": "listening"})
        elif t == "interrupt":
            await self.interrupt()
        elif t == "cancel_task":
            res = cancel_task(m.get("id") or "latest")
            if res.get("cancelled"):
                self.emit({"type": "task_update", "task": TASKS[res["cancelled"]]})

    # -- transcription
    async def on_word(self, word: str):
        if not word:
            return
        self.words.append(word)
        self.emit({"type": "user_partial", "text": join_words(self.words)})
        busy = (self.turn and not self.turn.done()) or self.playing
        if BARGE_IN and busy and len(self.words) >= 2:
            await self.interrupt()

    def on_vad(self, vad: list):
        if not self.words or self.ending or not vad:
            return
        step = min(vad, key=lambda v: abs(v.get("horizon_s", 0) - TURN_HORIZON))
        if step.get("inactivity_prob", 0) >= TURN_THRESHOLD:
            self.ending = True
            self.spawn(self.end_of_turn())

    async def end_of_turn(self):
        try:
            await self.stt.flush()
            text = join_words(self.words)
            self.words = []
        finally:
            self.ending = False
        if text:
            await self.user_said(text)

    async def user_said(self, text: str):
        await self.interrupt()
        self.emit({"type": "user_final", "text": text})
        self._add_user([{"type": "text", "text": text}])
        self.start_turn()

    async def interrupt(self):
        await self.cancel_turn()
        if self.playing:
            self.playing = False
            self.emit({"type": "clear_audio"})
        self.emit({"type": "state", "state": "listening"})

    # -- historique
    def _add_user(self, blocks: list):
        if self.history and self.history[-1]["role"] == "user":
            self.history[-1]["content"].extend(blocks)
        else:
            self.history.append({"role": "user", "content": list(blocks)})

    def _trim(self):
        h = self.history
        if len(h) > MAX_HISTORY:
            h = h[-MAX_HISTORY:]
            while h and not (h[0]["role"] == "user"
                             and all(b.get("type") == "text" for b in h[0]["content"])):
                h.pop(0)
            self.history = h

    def _repair(self, spoken: str):
        """Après une interruption, remettre l'historique dans un état valide."""
        last = self.history[-1] if self.history else None
        if last and last["role"] == "assistant":
            ids = [b["id"] for b in last["content"] if b.get("type") == "tool_use"]
            if ids:
                self.history.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": i, "is_error": True,
                     "content": "Interrompu par l'utilisateur."} for i in ids]})
        elif spoken.strip():
            self.history.append({"role": "assistant", "content": [
                {"type": "text", "text": spoken.strip() + " … [interrompu par l'utilisateur]"}]})

    # -- un tour de parole de VICTOR
    def start_turn(self):
        if self.closed:
            return
        self.turn = asyncio.create_task(self.respond())

    async def cancel_turn(self):
        t, self.turn = self.turn, None
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def respond(self):
        if self.inbox:
            self._add_user([{"type": "text", "text": x} for x in self.inbox])
            self.inbox.clear()
        if not self.history or self.history[-1]["role"] != "user":
            return
        self.emit({"type": "state", "state": "thinking"})
        tts = TTS(self)
        spoken = ""
        try:
            for _ in range(8):  # garde-fou contre les boucles d'outils
                self._trim()
                spoken = ""
                async with self.claude.messages.stream(
                    model=MODEL, max_tokens=1024, system=SYSTEM, tools=TOOLS,
                    messages=self.history,
                ) as stream:
                    async for delta in stream.text_stream:
                        spoken += delta
                        self.emit({"type": "assistant_text", "delta": delta})
                        await tts.say(delta)
                    final = await stream.get_final_message()
                content = []
                for b in final.content:
                    if b.type == "text" and b.text:
                        content.append({"type": "text", "text": b.text})
                    elif b.type == "tool_use":
                        content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                if not content:
                    content = [{"type": "text", "text": "…"}]
                self.history.append({"role": "assistant", "content": content})
                spoken = ""
                uses = [b for b in content if b["type"] == "tool_use"]
                if final.stop_reason != "tool_use" or not uses:
                    break
                await tts.flush_now()
                results = []
                for u in uses:
                    res = await self.run_tool(u["name"], u["input"])
                    results.append({"type": "tool_result", "tool_use_id": u["id"],
                                    "content": json.dumps(res, ensure_ascii=False)})
                self.history.append({"role": "user", "content": results})
            await tts.finish()
            self.emit({"type": "assistant_done"})
        except asyncio.CancelledError:
            self._repair(spoken)
            await tts.abort()
            raise
        except Exception as exc:  # noqa: BLE001
            self._repair(spoken)
            await tts.abort()
            self.emit({"type": "error", "message": f"Claude : {exc}"})
        finally:
            if not self.playing:
                self.emit({"type": "state", "state": "listening"})
        if self.inbox and not self.closed:
            self.start_turn()

    # -- outils
    async def run_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "delegate_to_claude":
                task = start_task(args.get("title") or "Tâche", args.get("prompt") or "")
                self.emit({"type": "task_started", "task": task})
                self.spawn(self.watch_task(task["id"]))
                return {"status": "started", "task_id": task["id"]}
            if name == "open_app":
                self.emit({"type": "card", "title": "Lancement", "kind": "info",
                           "content": f"Ouverture de **{args.get('name', '')}**"
                                      + (f" → écran **{args['monitor']}**" if args.get("monitor") else "")})
                return await asyncio.to_thread(open_target, name=args.get("name", ""),
                                               monitor=args.get("monitor"))
            if name == "open_url":
                self.emit({"type": "card", "title": "Lancement", "kind": "info",
                           "content": f"Ouverture de **{args.get('url', '')}**"})
                return await asyncio.to_thread(open_target, url=args.get("url", ""),
                                               monitor=args.get("monitor"))
            if name == "cancel_task":
                res = cancel_task(args.get("task_id") or "latest")
                if res.get("cancelled"):
                    self.emit({"type": "task_update", "task": TASKS[res["cancelled"]]})
                return res
            if name == "paste_to_window":
                target = args.get("target") or "click"
                if target == "click":
                    self.emit({"type": "card", "title": "Collage", "kind": "info",
                               "content": "Clique dans la fenêtre cible : collage dans 3 secondes."})
                return await asyncio.to_thread(paste_to_window, args.get("text", ""), target,
                                               bool(args.get("terminal")), bool(args.get("enter")))
            if name == "display_card":
                self.emit({"type": "card", "title": args.get("title", "Info"),
                           "content": args.get("content", ""), "kind": args.get("kind", "info")})
                return {"status": "displayed"}
            if name == "display_report":
                self.emit({"type": "report", "report": args})
                return {"status": "displayed"}
            return {"ok": False, "error": f"outil inconnu : {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def watch_task(self, task_id: str):
        task = TASKS[task_id]
        while task["status"] == "running":
            await asyncio.sleep(1)
        self.emit({"type": "task_update", "task": task})
        if task["status"] == "cancelled":
            return
        summary = (task["output"] or "").strip()[:4000]
        self.inbox.append(
            f"[SYSTÈME] Résultat de la tâche « {task['title']} » ({task['status']}) :\n{summary}\n"
            "Résume oralement en une ou deux phrases. S'il s'agit d'une analyse de "
            "données (chiffres, stats, comparatifs), affiche un tableau de bord avec "
            "display_report ; pour un résultat ponctuel, utilise display_card.")
        # Ne pas couper la parole : on attend que VICTOR et l'utilisateur se taisent.
        if not (self.turn and not self.turn.done()) and not self.words:
            self.start_turn()


@app.websocket("/ws")
async def voice_ws(ws: WebSocket):
    await ws.accept()
    await Session(ws).run()


# ---------------------------------------------------------------- réglages (roue crantée)

# Paramètres modifiables depuis l'interface. Les clés API et le port restent
# dans le .env uniquement (le port changerait l'adresse de la page elle-même).
GRADIUM_VOICES = {
    "iEu63s1rhn_kegTr": "Gaspard", "biuhvu17TxVKOcyy": "Marius", "YKeBw3OV1RgpdhLh": "Jules",
    "25AzBFyp6svYnJsj": "Damien", "Tek4tJXiX6_yvXq7": "Augustin", "6oIkS98REoVZ1dEw": "Apolline",
    "FXxJ9mANRq6BCTX5": "Noémie", "YhIHaAfQ0cQPDV9R": "Solène",
}
SETTINGS = [
    {"key": "VICTOR_TITRE", "group": "Général", "label": "Comment VICTOR t'appelle", "type": "text"},
    {"key": "VICTOR_LANGUAGE", "group": "Général", "label": "Langue", "type": "select",
     "options": {k: v for k, v in LANG_NAMES.items()}},
    {"key": "VICTOR_MODEL", "group": "Général", "label": "Modèle Claude du cerveau", "type": "text",
     "suggest": ["claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"]},
    {"key": "VICTOR_VOICE_ID", "group": "Gradium", "label": "Voix", "type": "select",
     "options": GRADIUM_VOICES},
    {"key": "GRADIUM_HOST", "group": "Gradium", "label": "Serveur", "type": "select",
     "options": {"eu.api.gradium.ai": "Europe", "us.api.gradium.ai": "États-Unis",
                 "api.gradium.ai": "Global"}},
    {"key": "VICTOR_STT_DELAY", "group": "Réactivité", "label": "Délai de transcription",
     "type": "range", "min": 7, "max": 55, "step": 1, "unit": "trames de 80 ms",
     "help": "7 = plus rapide, 55 = plus précis"},
    {"key": "VICTOR_TURN_HORIZON", "group": "Réactivité", "label": "Horizon de fin de phrase",
     "type": "range", "values": [0.5, 1.0, 2.0, 3.0], "unit": "s",
     "help": "Plus petit = réponse plus rapide, mais risque de te couper"},
    {"key": "VICTOR_TURN_THRESHOLD", "group": "Réactivité", "label": "Seuil de silence",
     "type": "range", "min": 0.05, "max": 0.95, "step": 0.05,
     "help": "Probabilité de silence à partir de laquelle VICTOR répond"},
    {"key": "VICTOR_BARGE_IN", "group": "Réactivité", "label": "Interrompre VICTOR en parlant",
     "type": "toggle", "help": "Désactive si VICTOR s'interrompt tout seul (haut-parleurs sans casque)"},
    {"key": "VICTOR_MIC_THRESHOLD", "group": "Économie de crédits", "label": "Seuil du micro",
     "type": "range", "min": 0, "max": 0.1, "step": 0.005,
     "help": "0 = transcription permanente (consomme en continu)"},
    {"key": "VICTOR_STT_IDLE_CLOSE", "group": "Économie de crédits", "label": "Mise en veille après",
     "type": "range", "min": 1, "max": 30, "step": 1, "unit": "s de silence"},
    {"key": "VICTOR_WORKDIR", "group": "Claude Code", "label": "Dossier de travail", "type": "text"},
    {"key": "VICTOR_TASK_TIMEOUT", "group": "Claude Code", "label": "Durée max d'une tâche",
     "type": "range", "min": 60, "max": 3600, "step": 60, "unit": "s"},
    {"key": "VICTOR_PERMISSION_MODE", "group": "Claude Code", "label": "Permissions", "type": "select",
     "options": {"bypassPermissions": "Tout autoriser", "acceptEdits": "Fichiers seulement",
                 "off": "Comportement d'origine"}},
]


def current_settings() -> dict:
    return {
        "VICTOR_TITRE": TITLE, "VICTOR_LANGUAGE": LANGUAGE, "VICTOR_MODEL": MODEL,
        "VICTOR_VOICE_ID": VOICE_ID, "GRADIUM_HOST": GRADIUM_HOST,
        "VICTOR_STT_DELAY": STT_DELAY, "VICTOR_TURN_HORIZON": TURN_HORIZON,
        "VICTOR_TURN_THRESHOLD": TURN_THRESHOLD, "VICTOR_BARGE_IN": BARGE_IN,
        "VICTOR_MIC_THRESHOLD": MIC_THRESHOLD, "VICTOR_STT_IDLE_CLOSE": STT_IDLE_CLOSE,
        "VICTOR_WORKDIR": WORKDIR, "VICTOR_TASK_TIMEOUT": TASK_TIMEOUT,
        "VICTOR_PERMISSION_MODE": PERMISSION_MODE,
    }


def _validate_setting(spec: dict, raw) -> str:
    """Renvoie la valeur telle qu'elle sera écrite dans le .env, ou lève ValueError."""
    kind = spec["type"]
    if kind == "toggle":
        return "1" if raw in (True, 1, "1", "true", "on") else "0"
    if kind == "range":
        v = float(raw)
        if "values" in spec:
            v = min(spec["values"], key=lambda x: abs(x - v))
        elif not spec["min"] <= v <= spec["max"]:
            raise ValueError(f"hors limites ({spec['min']} – {spec['max']})")
        return f"{v:g}"
    v = str(raw).strip()
    if not v or any(c in v for c in "\r\n"):
        raise ValueError("valeur vide ou invalide")
    if kind == "select" and v not in spec["options"]:
        raise ValueError("choix inconnu")
    if spec["key"] == "VICTOR_WORKDIR" and not os.path.isdir(os.path.expanduser(v)):
        raise ValueError(f"le dossier {v} n'existe pas")
    return v


def write_env(values: dict):
    """Met à jour le .env en gardant ses commentaires : remplace la ligne active,
    sinon décommente la ligne d'exemple, sinon ajoute la variable à la fin."""
    env_file = ROOT / ".env"
    lines = env_file.read_text(encoding="utf-8-sig").splitlines() if env_file.exists() else []
    pending = dict(values)

    def fmt(k, v):
        return f'{k}="{v}"' if (" " in v or "#" in v) else f"{k}={v}"

    for active in (True, False):
        for i, line in enumerate(lines):
            m = re.match(r"\s*(#\s*)?([A-Z_][A-Z0-9_]*)\s*=", line)
            if m and m.group(2) in pending and (m.group(1) is None) == active:
                lines[i] = fmt(m.group(2), pending.pop(m.group(2)))
    if pending:
        lines += ["", "# --- Réglages enregistrés depuis l'interface"]
        lines += [fmt(k, v) for k, v in pending.items()]
    tmp = env_file.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, env_file)


def restart_server():
    """Relance ce processus : les nouveaux réglages sont relus au démarrage."""
    for proc in list(PROCS.values()):
        _kill_tree(proc)
    if IS_WINDOWS:
        subprocess.Popen([sys.executable] + sys.argv, cwd=ROOT)
        os._exit(0)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.get("/api/settings")
def api_get_settings():
    return {"schema": SETTINGS, "values": current_settings(),
            "busy": sum(t.get("status") == "running" for t in TASKS.values())}


@app.post("/api/settings")
async def api_save_settings(payload: dict):
    specs = {s["key"]: s for s in SETTINGS}
    clean, errors = {}, {}
    for k, raw in payload.items():
        if k not in specs:
            continue
        try:
            clean[k] = _validate_setting(specs[k], raw)
        except (TypeError, ValueError) as exc:
            errors[k] = str(exc)
    if errors:
        raise HTTPException(422, detail=errors)
    write_env(clean)
    # load_env() n'écrase pas les variables déjà présentes, et le processus relancé
    # hérite de cet environnement : on y met donc les nouvelles valeurs.
    os.environ.update(clean)
    asyncio.get_running_loop().call_later(0.5, restart_server)
    return {"ok": True, "saved": clean}


# ---------------------------------------------------------------- static

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


if __name__ == "__main__":
    import uvicorn
    missing = [n for n, v in (("GRADIUM_API_KEY", GRADIUM_API_KEY),
                              ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)) if not v]
    if missing:
        print(f"\n  ⚠  {', '.join(missing)} manquant : copie .env.example vers .env et remplis-le.")
    print(f"\n  VICTOR Local -> http://127.0.0.1:{PORT}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
