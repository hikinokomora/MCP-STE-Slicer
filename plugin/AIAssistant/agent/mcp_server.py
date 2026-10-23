"""MCP server core: JSON-RPC 2.0 over HTTP (POST /mcp), methods initialize, tools/list, tools/call."""
import json
import traceback

from UM.Logger import Logger

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "ste-slicer-ai-assistant", "version": "1.0.0"}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class MCPServer:
    def __init__(self, registry, bus):
        self._registry = registry
        self._bus = bus

    def handle_raw(self, body):
        try:
            payload = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
        except ValueError:
            return _error(None, -32700, "Parse error")
        if isinstance(payload, list):
            responses = [r for r in (self.handle(p) for p in payload) if r is not None]
            return responses or None
        return self.handle(payload)

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or "method" not in request:
            return _error(request.get("id") if isinstance(request, dict) else None, -32600, "Invalid Request")
        method = request["method"]
        request_id = request.get("id")
        params = request.get("params") or {}
        is_notification = "id" not in request

        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": SERVER_INFO,
                      "instructions": "Инструменты управляют STE Slicer: настройки, профили, материалы, режим 3D/5D, модели, слайсинг, экспорт."}
        elif method in ("notifications/initialized", "initialized"):
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self._registry.mcp_list()}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            result = self.call_tool(name, arguments, source="mcp")
        else:
            return None if is_notification else _error(request_id, -32601, "Method not found: %s" % method)
        return None if is_notification else _result(request_id, result)

    def call_tool(self, name, arguments, source="agent"):
        """Execute a tool and return an MCP CallToolResult; also streams events to the chat UI."""
        call = self._bus.emit("tool_call", name=name, arguments=arguments, source=source,
                              group=self._registry.group_of(name))
        try:
            data = self._registry.call(name, arguments)
            is_error = False
        except Exception as e:  # tool errors are returned to the model, not raised
            if e.__class__.__name__ != "ToolError":
                Logger.log("e", "AIAssistant tool %s failed: %s", name, traceback.format_exc())
            data = {"error": str(e)}
            is_error = True
        self._bus.emit("tool_result", call_id=call["id"], name=name, result=data, is_error=is_error, source=source)
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}],
                "isError": is_error, "structuredContent": data if isinstance(data, dict) else {"result": data}}
