"""Minimal OpenAI-compatible Chat Completions client on urllib (Python 3.5)."""
import json
import os
import ssl
import urllib.error
import urllib.request

from UM.Logger import Logger

# Public root CAs newer than the certifi bundle shipped with STE Slicer (2020),
# e.g. GlobalSign Root R46 used by api.timeweb.ai.
EXTRA_ROOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "extra_roots.pem")


class LLMError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


_context = None


def _ssl_context():
    """Windows certificate store + the slicer's certifi bundle + bundled newer roots."""
    global _context
    if _context is not None:
        return _context
    context = ssl.create_default_context()  # loads the Windows ROOT/CA stores
    sources = [EXTRA_ROOTS]
    try:
        import certifi
        sources.append(certifi.where())
    except Exception:
        pass
    for path in sources:
        try:
            context.load_verify_locations(cafile=path)
        except Exception as e:
            Logger.log("w", "AIAssistant: cannot load CA bundle %s: %s", path, e)
    _context = context
    return context


# Qwen 3 "thinks" before every step: up to 6000 hidden reasoning tokens per step (~90 s at this provider).
# A budget keeps the reasoning but caps it. Providers that do not know the parameter answer HTTP 400:
# then it is dropped for the rest of the session.
THINKING_BUDGET = 1024
_thinking_param_supported = True


class LLMClient:
    def __init__(self, base_url, api_key, model, timeout=240):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout

    def is_configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def chat(self, messages, tools=None, temperature=0.2):
        global _thinking_param_supported
        if not self.is_configured():
            raise LLMError("LLM не настроена: укажите Base URL, API key и модель в настройках чата.")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if _thinking_param_supported and "qwen" in self.model.lower():
            payload["thinking_budget"] = THINKING_BUDGET
        try:
            return self._post(payload)
        except LLMError as e:
            if "thinking_budget" in payload and str(e).startswith("LLM вернула HTTP 400"):
                _thinking_param_supported = False  # the provider does not accept it: work without the budget
                payload.pop("thinking_budget")
                return self._post(payload)
            raise

    def _post(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            raise LLMError("LLM вернула HTTP %s: %s" % (e.code, detail), retryable=e.code == 429 or e.code >= 500)
        except urllib.error.URLError as e:
            reason = str(e.reason)
            raise LLMError("Нет связи с LLM (%s): %s" % (self.base_url, reason), retryable="CERTIFICATE" not in reason)
        except Exception as e:  # socket.timeout, connection reset, bad JSON
            raise LLMError("Ошибка запроса к LLM: %s" % e, retryable=True)

        choices = body.get("choices") or []
        if not choices:
            raise LLMError("LLM вернула пустой ответ: %s" % json.dumps(body, ensure_ascii=False)[:500])
        return choices[0].get("message") or {}, body.get("usage") or {}
