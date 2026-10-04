"""Empty HTTP entry point. No model, prompt, routing, business tools or agent loop."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"status": "ok", "agent_implemented": False})
        else:
            self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/chat":
            self.respond(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                raise ValueError()
            if not data["message"].strip() or len(data["message"]) > 2000:
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            self.respond(
                400,
                {"error": "Expected a nonempty message of at most 2000 characters."},
            )
            return
        self.respond(
            200,
            {
                "reply": "Agent 尚未实现。页面与独立服务已连通；提示词、模型调用和业务操作将由你在后续练习中完成。",
                "implemented": False,
            },
        )


def main():
    port = int(os.environ.get("AGENT_PORT", "8001"))
    print(f"Agent empty service: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
