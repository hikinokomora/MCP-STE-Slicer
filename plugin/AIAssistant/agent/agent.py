# -*- coding: utf-8 -*-
"""Dialogue loop: user message -> LLM -> MCP tool calls -> LLM -> ... -> answer."""
import base64
import importlib
import json
import os
import re
import threading
import time
import traceback
import zipfile

from UM.Logger import Logger

from . import knowledge
from .llm_client import LLMClient, LLMError

MAX_STEPS = 40
MAX_TOOL_RESULT_CHARS = 8000
IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MODEL_EXT = (".stl", ".obj", ".3mf")
TEXT_EXT = (".txt", ".md", ".csv", ".json")
SAVE_TOOLS = ("save_project", "export_gcode")
SAVE_REQUEST_RE = re.compile(r"сохран|экспорт|save|export", re.IGNORECASE)
SAVE_REFUSAL_RE = re.compile(r"\bне\s+(надо\s+|нужно\s+)?(сохран|экспорт)", re.IGNORECASE)


def extract_docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for src, dst in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(src, dst)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class Agent:
    def __init__(self, mcp, registry, bus, settings_provider):
        self._mcp = mcp
        self._registry = registry
        self._bus = bus
        self._settings = settings_provider
        self._lock = threading.Lock()
        self._busy = False
        self._stop = False
        self._messages = []
        self._save_approved = False
        self._unsaved_slice = False
        self.reset()

    def reset(self):
        try:
            importlib.reload(knowledge)
        except Exception:
            Logger.logException("w", "AIAssistant: could not reload the knowledge base")
        self._messages = [{"role": "system", "content": knowledge.SYSTEM_PROMPT}]
        self._unsaved_slice = False

    def is_busy(self):
        return self._busy

    def stop(self):
        self._stop = True

    def submit(self, text, attachments, approve_save=False):
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            text_l = text or ""
            self._save_approved = bool(approve_save) or (
                bool(SAVE_REQUEST_RE.search(text_l)) and not SAVE_REFUSAL_RE.search(text_l))
            self._stop = False
        threading.Thread(target=self._run, args=(text, attachments), daemon=True).start()
        return True

    def _build_user_content(self, text, attachments):
        parts_text = [text.strip()] if text and text.strip() else []
        images = []
        for att in attachments or []:
            path = att.get("path")
            name = att.get("name") or os.path.basename(path or "")
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXT:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode("ascii")
                images.append({"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (IMAGE_EXT[ext], data)}})
                parts_text.append("[Приложено изображение: %s]" % name)
            elif ext in MODEL_EXT:
                parts_text.append("[Приложена 3D-модель: %s — путь для load_model: %s]" % (name, path))
            elif ext == ".docx":
                try:
                    parts_text.append("[Приложен документ %s]\n%s" % (name, extract_docx_text(path)))
                except Exception as e:
                    parts_text.append("[Документ %s не прочитан: %s]" % (name, e))
            elif ext in TEXT_EXT:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    parts_text.append("[Приложен файл %s]\n%s" % (name, f.read()[:20000]))
            else:
                parts_text.append("[Приложен файл %s (формат не поддерживается)]" % name)
        text_block = "\n\n".join(parts_text) or "(пустое сообщение)"
        if images:
            return [{"type": "text", "text": text_block}] + images, True
        return text_block, False

    def _run(self, text, attachments):
        try:
            content, has_images = self._build_user_content(text, attachments)
            self._messages.append({"role": "user", "content": content})
            self._bus.emit("status", state="thinking")
            base_url, api_key, model = self._settings()
            client = LLMClient(base_url, api_key, model)
            tools = self._registry.openai_tools()

            for step in range(MAX_STEPS):
                if self._stop:
                    self._bus.emit("assistant_message", text="Остановлено пользователем.")
                    break
                try:
                    started = time.time()
                    message, usage = self._chat_with_retry(client, tools)
                    Logger.log("i", "AIAssistant: LLM step %d took %.1f s, tool calls: %s, usage: %s", step + 1,
                               time.time() - started,
                               [(c.get("function") or {}).get("name") for c in (message.get("tool_calls") or [])], usage)
                except LLMError as e:
                    if has_images and not e.retryable:
                        self._strip_images()
                        has_images = False
                        self._bus.emit("warning", text="LLM не приняла изображение, повторяю запрос без него: %s" % e)
                        continue
                    raise
                tool_calls = message.get("tool_calls") or []
                assistant_entry = {"role": "assistant", "content": message.get("content") or ""}
                if tool_calls:
                    assistant_entry["tool_calls"] = tool_calls
                self._messages.append(assistant_entry)
                if usage:
                    self._bus.emit("usage", usage=usage)

                if not tool_calls:
                    self._bus.emit("assistant_message", text=message.get("content") or "")
                    break
                if message.get("content"):
                    self._bus.emit("assistant_note", text=message["content"])
                for call in tool_calls:
                    if self._stop:
                        break
                    self._execute(call)
                self._bus.emit("status", state="thinking")
            else:
                self._bus.emit("warning", text="Достигнут лимит шагов агента (%d)." % MAX_STEPS)
        except LLMError as e:
            self._bus.emit("error", text=str(e))
        except Exception as e:
            Logger.log("e", "AIAssistant agent crashed: %s", traceback.format_exc())
            self._bus.emit("error", text="Внутренняя ошибка агента: %s" % e)
        finally:
            if self._unsaved_slice and not self._stop:
                self._bus.emit("save_offer")
            self._busy = False
            self._bus.emit("status", state="idle")

    def _chat_with_retry(self, client, tools, attempts=3):
        for attempt in range(1, attempts + 1):
            try:
                return client.chat(self._messages, tools=tools)
            except LLMError as e:
                if not e.retryable or attempt == attempts or self._stop:
                    raise
                delay = 3 * attempt
                self._bus.emit("warning", text="LLM не ответила (%s). Повтор %d из %d через %d с…" % (e, attempt, attempts - 1, delay))
                time.sleep(delay)

    def _execute(self, call):
        function = call.get("function") or {}
        name = function.get("name", "")
        raw_args = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except ValueError:
            arguments = None
        if arguments is None:
            text = json.dumps({"error": "Аргументы не являются корректным JSON: %s" % raw_args[:300]}, ensure_ascii=False)
        elif name in SAVE_TOOLS and not self._save_approved:
            text = json.dumps({"error": "Файлы сохраняются только после подтверждения пользователя. Не сохраняй: "
                                        "закончи итогом и спроси, сохранить ли проект (3MF) и G-code."},
                              ensure_ascii=False)
        else:
            started = time.time()
            result = self._mcp.call_tool(name, arguments, source="agent")
            text = result["content"][0]["text"]
            Logger.log("i", "AIAssistant: tool %s took %.1f s, args: %s", name, time.time() - started,
                       json.dumps(arguments, ensure_ascii=False)[:500])
            if not result.get("isError"):
                if name == "slice":
                    self._unsaved_slice = True
                elif name == "save_project":
                    self._unsaved_slice = False
                    self._bus.emit("save_offer_clear")
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "...(обрезано)"
        self._messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": text})

    def _strip_images(self):
        for msg in self._messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                msg["content"] = "\n".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
