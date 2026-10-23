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
from urllib.parse import parse_qs, unquote, urlparse

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Resources import Resources

from .agent.agent import Agent
from .agent.events import EventBus
from .agent.llm_client import LLMClient, LLMError
from .agent.mcp_server import MCPServer
from .agent.slicer_api import SlicerAPI
from .agent.tools import ToolRegistry

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(PLUGIN_DIR, "web")
PREFERRED_PORT = 8765
PREF = "ai_assistant/"
DEFAULTS = {
    "base_url": "https://api.timeweb.ai/v1",
    "model": "dashscope/qwen3.8-flash",
    "api_key": "",
    "output_dir": os.path.join(os.path.expanduser("~"), "Documents", "STE Slicer AI Results"),
}
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
        self._registry = ToolRegistry(self._api, lambda: self.getSetting("output_dir"))
        self._mcp = MCPServer(self._registry, self._bus)
        self._agent = Agent(self._mcp, self._registry, self._bus, self._llmSettings)
        self._uploads = {}
        self._server = None
        self._server_lock = threading.Lock()
        self._upload_dir = os.path.join(Resources.getDataStoragePath(), "ai_assistant", "uploads")

        # start the server once the UI is up so external MCP clients can connect right away
        self._app.engineCreatedSignal.connect(self._startServer)

    # ------------------------------------------------------------------ settings
    def getSetting(self, key):
        value = self._app.getPreferences().getValue(PREF + key)
        return value if value not in (None, "") else DEFAULTS.get(key, "")

    def setSetting(self, key, value):
        self._app.getPreferences().setValue(PREF + key, value)

    def _llmSettings(self):
        return self.getSetting("base_url"), self.getSetting("api_key"), self.getSetting("model")

    # ------------------------------------------------------------------ menu
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
        webbrowser.open(self.url())

    def showSettings(self):
        webbrowser.open(self.url("#settings"))

    def openOutputDir(self):
        path = self.getSetting("output_dir")
        os.makedirs(path, exist_ok=True)
        os.startfile(path) if hasattr(os, "startfile") else webbrowser.open("file://" + path)

    # ------------------------------------------------------------------ API used by the handler
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

        def log_message(self, fmt, *args):  # keep the slicer log clean
            pass

        # -------------------------------------------------------------- utils
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

        # -------------------------------------------------------------- GET
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
                elif path == "/mcp":
                    self._send(405, {"error": "Use POST with JSON-RPC 2.0"})
                elif path == "/api/debug/threads":
                    # stacks of all Python threads; answers even when the Qt main thread hangs
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

        # -------------------------------------------------------------- POST
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
                    if not ext._agent.submit(text, attachments):
                        self._send(409, {"error": "Агент ещё отвечает на предыдущее сообщение"})
                        return
                    self._send(200, {"ok": True})
                elif path == "/api/upload":
                    name = parse_qs(parsed.query).get("name", ["file"])[0]
                    self._send(200, ext.store_upload(name, self._body()))
                elif path == "/api/settings":
                    self._send(200, ext.update_settings(self._json()))
                elif path == "/api/test_llm":
                    try:
                        self._send(200, ext.test_llm())
                    except LLMError as e:
                        self._send(200, {"ok": False, "error": str(e)})
                elif path == "/api/stop":
                    ext._agent.stop()
                    self._send(200, {"ok": True})
                elif path == "/api/reset":
                    if ext._agent.is_busy():
                        self._send(409, {"error": "Агент занят"})
                        return
                    ext._agent.reset()
                    ext._bus.clear()
                    self._send(200, {"ok": True})
                elif path == "/api/tool":
                    # direct tool call from the UI (quick actions)
                    data = self._json()
                    self._send(200, ext._mcp.call_tool(data.get("name"), data.get("arguments") or {}, source="ui"))
                else:
                    self._send(404, {"error": "not found"})
            except Exception as e:
                Logger.logException("e", "AIAssistant POST %s failed", path)
                self._send(500, {"error": str(e)})

    return Handler
