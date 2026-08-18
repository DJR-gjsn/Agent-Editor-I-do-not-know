"""测试用迷你 MCP server（stdio + http 双模式）— 仅用于单元测试"""
import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "回显消息",
     "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}},
                     "required": ["message"]}},
    {"name": "fail", "description": "固定失败",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "sleep", "description": "休眠指定秒数",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
]


def handle_request(req):
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": "1.0", "capabilities": {},
                "serverInfo": {"name": "mini-mcp", "version": "0.1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            return {"content": [{"type": "text", "text": args.get("message", "")}],
                    "isError": False}
        if name == "fail":
            return {"content": [{"type": "text", "text": "故意失败"}], "isError": True}
        if name == "sleep":
            time.sleep(float(args.get("seconds", 1)))
            return {"content": [{"type": "text", "text": "slept"}], "isError": False}
        return {"content": [{"type": "text", "text": "未知工具 " + str(name)}],
                "isError": True}
    return {"error": {"code": -32601, "message": "未知方法 " + str(method)}}


def run_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        if rid is None:  # notification，不响应
            continue
        try:
            result = handle_request(req)
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
        except Exception as e:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": rid,
                 "error": {"code": -32603, "message": str(e)}}) + "\n")
        sys.stdout.flush()


def run_http(port):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body.decode("utf-8"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            rid = req.get("id")
            if rid is None:
                self.send_response(202)
                self.end_headers()
                return
            try:
                result = handle_request(req)
                payload = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result})
                status = 200
            except Exception as e:
                payload = json.dumps(
                    {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": -32603, "message": str(e)}})
                status = 200
            data = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"port": srv.server_port}), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        run_http(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    else:
        run_stdio()
