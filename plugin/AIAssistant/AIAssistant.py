# -*- coding: utf-8 -*-
"""AI Assistant extension: menu entry, local HTTP server (SPA + REST + MCP), agent wiring."""
import json
import mimetypes
import os
import re
import sys
import threading
import traceback
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.request

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Resources import Resources

from .agent import corrections
from .agent.agent import Agent
from .agent.events import EventBus
from .agent.llm_client import LLMClient, LLMError, _ssl_context
from .agent.mcp_server import MCPServer
from .agent.slicer_api import SlicerAPI
from .agent.tools import ToolRegistry
from .dock import DockedChatWindow

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(PLUGIN_DIR, "web")
PREFERRED_PORT = 8765
PREF = "ai_assistant/"
DEFAULTS = {
    "base_url": "https://api.timeweb.ai/v1",
    "model": "dashscope/qwen3.8-flash",
    "api_key": "",
    "output_dir": os.path.join(os.path.expanduser("~"), "Documents", "STE Slicer AI Results"),
    "corrections_repo": "hikinokomora/MCP-STE-Slicer",
    "install_id": "",
}
CORRECTION_LLM_PROMPT = (
    "Ты проверяешь корректировку подбора материала для FDM-печати. Тебе даны только структурированные данные. "
    "Оцени, разумна ли она инженерно: подходит ли предлагаемый материал под условие и требования лучше или не хуже "
    "базового выбора. Ответь строго JSON без пояснений вокруг: {\"verdict\": \"ok\" или \"reject\", \"reason\": \"кратко\"}.")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class ChatServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class AIAssistant(Extension):
    def __init__(self):
        super().__init__()
        self.setMenuName("AI Assistant")
        self.addMenuItem("Открыть чат", self.showChat)
        self.addMenuItem("Настройки LLM", self.showSettings)
        self.addMenuItem("Папка результатов", self.openOutputDir)

        self._app = Application.getInstance()
        preferences = self._app.getPreferences()
        for key, value in DEFAULTS.items():
            preferences.addPreference(PREF + key, value)

        self._bus = EventBus()
        self._api = SlicerAPI(self._app, self._bus)
        data_dir = os.path.join(Resources.getDataStoragePath(), "ai_assistant")
        self._corrections = corrections.Store(data_dir, lambda msg: Logger.log("w", msg))
        self._registry = ToolRegistry(self._api, lambda: self.getSetting("output_dir"), self._corrections, self._bus)
        self._mcp = MCPServer(self._registry, self._bus)
        self._agent = Agent(self._mcp, self._registry, self._bus, self._llmSettings)
        self._uploads = {}
        self._server = None
        self._server_lock = threading.Lock()
        self._upload_dir = os.path.join(Resources.getDataStoragePath(), "ai_assistant", "uploads")
        self._dock = DockedChatWindow(self._app, os.path.join(Resources.getDataStoragePath(), "ai_assistant", "edge_profile"))

        self._app.engineCreatedSignal.connect(self._startServer)
        threading.Thread(target=self._fetchGlobalCorrections, daemon=True).start()

    def getSetting(self, key):
        value = self._app.getPreferences().getValue(PREF + key)
        return value if value not in (None, "") else DEFAULTS.get(key, "")

    def setSetting(self, key, value):
        self._app.getPreferences().setValue(PREF + key, value)

    def _llmSettings(self):
        return self.getSetting("base_url"), self.getSetting("api_key"), self.getSetting("model")

    def _startServer(self):
        with self._server_lock:
            if self._server is not None:
                return self._server.server_port
            handler = _make_handler(self)
            try:
                self._server = ChatServer(("127.0.0.1", PREFERRED_PORT), handler)
            except OSError:
                self._server = ChatServer(("127.0.0.1", 0), handler)
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
            Logger.log("i", "AI Assistant server on http://127.0.0.1:%d/ (MCP: /mcp)", self._server.server_port)
            return self._server.server_port

    def url(self, fragment=""):
        return "http://127.0.0.1:%d/%s" % (self._startServer(), fragment)

    def showChat(self):
        url = self.url()
        if not self._dock.open(url):
            webbrowser.open(url)

    def showSettings(self):
        if self._dock.available() and self._dock.is_open():
            self._bus.emit("open_settings")
            self._dock.open(self.url())
            return
        url = self.url("#settings")
        if not self._dock.open(url):
            webbrowser.open(url)

    def openOutputDir(self):
        path = self.getSetting("output_dir")
        os.makedirs(path, exist_ok=True)
        os.startfile(path) if hasattr(os, "startfile") else webbrowser.open("file://" + path)

    def install_id(self):
        """Random id of this installation: one vote per installation, no personal data."""
        value = self.getSetting("install_id")
        if not value:
            value = uuid.uuid4().hex
            self.setSetting("install_id", value)
        return value

    def _globalUrl(self):
        return "https://raw.githubusercontent.com/%s/main/corrections/global.json" % self.getSetting("corrections_repo")

    def _fetchGlobalCorrections(self):
        try:
            with urllib.request.urlopen(self._globalUrl(), timeout=15, context=_ssl_context()) as response:
                data = json.loads(response.read().decode("utf-8"))
            count = self._corrections.save_global_cache(data)
            Logger.log("i", "AIAssistant: loaded %d global corrections", count)
        except Exception as e:
            Logger.log("w", "AIAssistant: global corrections not updated (%s), using the cached copy", e)

    def corrections_payload(self):
        def view(c):
            return {"id": c["id"], "text": corrections.describe(c), "comment": c.get("comment", ""),
                    "scope": c.get("scope", c.get("source")), "created": c.get("created")}
        return {"local": [view(c) for c in self._corrections.local()],
                "global": [view(c) for c in self._corrections.global_()],
                "repo": self.getSetting("corrections_repo")}

    def _llm_check(self, corr):
        """Extra filter for corrections proposed to everyone: the LLM can only reject, never approve on its own.
        It sees structured fields and material data only, not the user's free-text comment."""
        from .agent import knowledge
        kind, material = list(corr["action"].items())[0]
        reqs = (corr.get("context") or {}).get("requirements") or {}
        ranked = knowledge.score_materials(reqs) if reqs else []
        facts = {"condition": corrections.describe_condition(corr["conditions"]), "action": kind,
                 "material": knowledge.material_card(material),
                 "spec_requirements": reqs,
                 "base_choice_without_correction": knowledge.material_card(ranked[0]["id"]) if ranked else None}
        client = LLMClient(*self._llmSettings(), timeout=60)
        message, _ = client.chat([{"role": "system", "content": CORRECTION_LLM_PROMPT},
                                  {"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=str)}])
        text = message.get("content") or ""
        match = re.search(r"\{.*\}", text, re.S)
        verdict = json.loads(match.group(0)) if match else {}
        if verdict.get("verdict") != "ok":
            return "Проверка ИИ отклонила корректировку: %s" % (verdict.get("reason") or "ответ не распознан")
        return None

    def save_correction(self, corr, scope):
        problems = corrections.validate(corr)
        if problems:
            return {"ok": False, "problems": problems}
        if scope == "global":
            try:
                problem = self._llm_check(corr)
            except Exception as e:
                problem = "Проверка ИИ недоступна (%s), попробуйте позже или сохраните только у себя" % e
            if problem:
                return {"ok": False, "problems": [problem]}
        saved = self._corrections.add_local(corr, proposed=(scope == "global"))
        result = {"ok": True, "text": corrections.describe(saved), "scope": saved["scope"]}
        if scope == "global":
            title = "[correction] %s" % corrections.describe(saved)
            result["issue_url"] = "https://github.com/%s/issues/new?title=%s&body=%s" % (
                self.getSetting("corrections_repo"), quote(title[:200]),
                quote(corrections.issue_body(saved, self.install_id())))
        Logger.log("i", "AIAssistant: correction saved (%s): %s", saved["scope"], result["text"])
        return result

    def store_upload(self, name, data):
        os.makedirs(self._upload_dir, exist_ok=True)
        safe = re.sub(r"[\\/:*?\"<>|]+", "_", os.path.basename(name)) or "file"
        upload_id = uuid.uuid4().hex[:12]
        folder = os.path.join(self._upload_dir, upload_id)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe)
        with open(path, "wb") as f:
            f.write(data)
        info = {"id": upload_id, "name": safe, "path": path, "size": len(data)}
        self._uploads[upload_id] = info
        self._api.remember_upload(safe, path)
        return info

    LOCAL_ATTACH_EXT = (".stl", ".obj", ".3mf", ".jpg", ".jpeg", ".png", ".docx", ".txt")

    def register_local_file(self, path):
        """Attach a file that is already on this computer without copying it
        (POST /api/upload?path=...; used by scripted runs and external tools)."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise ValueError("Файл не найден: %s" % path)
        if os.path.splitext(path)[1].lower() not in self.LOCAL_ATTACH_EXT:
            raise ValueError("Неподдерживаемый тип файла: %s" % os.path.basename(path))
        upload_id = uuid.uuid4().hex[:12]
        info = {"id": upload_id, "name": os.path.basename(path), "path": path, "size": os.path.getsize(path)}
        self._uploads[upload_id] = info
        self._api.remember_upload(info["name"], path)
        return info

    def settings_payload(self):
        key = self.getSetting("api_key")
        return {"base_url": self.getSetting("base_url"), "model": self.getSetting("model"),
                "has_key": bool(key), "key_hint": ("…" + key[-4:]) if len(key) > 8 else "",
                "output_dir": self.getSetting("output_dir"), "port": self._server.server_port if self._server else None}

    def update_settings(self, data):
        for key in ("base_url", "model", "output_dir"):
            if key in data and data[key] is not None:
                self.setSetting(key, str(data[key]).strip())
        if data.get("api_key"):
            self.setSetting("api_key", str(data["api_key"]).strip())
        return self.settings_payload()

    def test_llm(self):
        client = LLMClient(*self._llmSettings(), timeout=60)
        started = time.time()
        message, _ = client.chat([{"role": "user", "content": "Ответь одним словом: готов?"}])
        return {"ok": True, "reply": (message.get("content") or "")[:200], "latency_s": round(time.time() - started, 2)}


def _make_handler(ext):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > MAX_UPLOAD_BYTES:
                raise ValueError("Файл слишком большой")
            return self.rfile.read(length) if length else b""

        def _json(self):
            raw = self._body()
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _local_origin(self):
            origin = self.headers.get("Origin")
            return origin is None or origin.startswith(("http://127.0.0.1", "http://localhost"))

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == "/api/events":
                    after = int(query.get("after", ["0"])[0])
                    self._send(200, {"events": ext._bus.since(after, wait=20.0), "busy": ext._agent.is_busy()})
                elif path == "/api/settings":
                    self._send(200, ext.settings_payload())
                elif path == "/api/state":
                    self._send(200, {"scene": ext._api.scene_info(), "slice": ext._api.slice_status(),
                                     "busy": ext._agent.is_busy()})
                elif path == "/api/tools":
                    self._send(200, {"tools": ext._registry.mcp_list()})
                elif path == "/api/corrections":
                    self._send(200, ext.corrections_payload())
                elif path == "/mcp":
                    self._send(405, {"error": "Use POST with JSON-RPC 2.0"})
                elif path == "/api/debug/threads":
                    names = {t.ident: t.name for t in threading.enumerate()}
                    dump = []
                    for ident, frame in sys._current_frames().items():
                        dump.append("--- %s (%s)\n%s" % (names.get(ident, "?"), ident, "".join(traceback.format_stack(frame))))
                    self._send(200, "\n".join(dump), "text/plain; charset=utf-8")
                else:
                    self._static(path)
            except Exception as e:
                Logger.logException("e", "AIAssistant GET %s failed", path)
                self._send(500, {"error": str(e)})

        def _static(self, path):
            rel = unquote(path).lstrip("/") or "index.html"
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(full):
                self._send(404, {"error": "not found"})
                return
            ext_types = {".js": "application/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}
            ctype = ext_types.get(os.path.splitext(full)[1].lower()) or mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._local_origin():
                self._send(403, {"error": "forbidden origin"})
                return
            try:
                if path == "/mcp":
                    response = ext._mcp.handle_raw(self._body())
                    if response is None:
                        self._send(202, b"")
                    else:
                        self._send(200, response)
                elif path == "/api/message":
                    data = self._json()
                    attachments = [ext._uploads[i] for i in data.get("attachments", []) if i in ext._uploads]
                    text = data.get("text", "")
                    ext._bus.emit("user_message", text=text,
                                  attachments=[{"name": a["name"], "id": a["id"]} for a in attachments])
                    if not ext._agent.submit(text, attachments, approve_save=bool(data.get("approve_save"))):
                        self._send(409, {"error": "Агент ещё отвечает на предыдущее сообщение"})
                        return
                    self._send(200, {"ok": True})
                elif path == "/api/upload":
                    query = parse_qs(parsed.query)
                    if query.get("path"):
                        self._send(200, ext.register_local_file(query["path"][0]))
                    else:
                        self._send(200, ext.store_upload(query.get("name", ["file"])[0], self._body()))
                elif path == "/api/settings":
                    self._send(200, ext.update_settings(self._json()))
                elif path == "/api/test_llm":
                    try:
                        self._send(200, ext.test_llm())
                    except LLMError as e:
                        self._send(200, {"ok": False, "error": str(e)})
                elif path == "/api/stop":
                    ext._agent.stop()
                    ext._api.cancel_slice()
                    self._send(200, {"ok": True})
                elif path == "/api/reset":
                    if ext._agent.is_busy():
                        self._send(409, {"error": "Агент занят"})
                        return
                    ext._agent.reset()
                    ext._bus.clear()
                    self._send(200, {"ok": True})
                elif path == "/api/corrections/save":
                    data = self._json()
                    self._send(200, ext.save_correction(data.get("correction") or {}, data.get("scope") or "local"))
                elif path == "/api/corrections/delete":
                    self._send(200, {"ok": ext._corrections.delete_local(str(self._json().get("id", "")))})
                elif path == "/api/tool":
                    data = self._json()
                    self._send(200, ext._mcp.call_tool(data.get("name"), data.get("arguments") or {}, source="ui"))
                else:
                    self._send(404, {"error": "not found"})
            except Exception as e:
                Logger.logException("e", "AIAssistant POST %s failed", path)
                self._send(500, {"error": str(e)})

    return Handler
