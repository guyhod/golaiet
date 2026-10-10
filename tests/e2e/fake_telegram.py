#!/usr/bin/env python3
"""The two Bot API methods Golaiet uses, as a stand-in for the end-to-end
stack. getUpdates long-polls a queue; sendMessage records. Two extra routes
belong to the test driver: POST /test/inbound {"text"} queues a message from
Guy's chat, GET /test/outbound lists everything the bot sent.

Stdlib only: it runs in a bare python image."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAT_ID = 1
MAX_WAIT_SEC = 30

updates: list[dict] = []
sent: list[dict] = []
changed = threading.Condition()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _json(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _reply(self, body: dict, status: int = 200):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/test/outbound":
            return self._reply(sent)
        self._reply({"ok": False, "description": "no such route"}, 404)

    def do_POST(self):
        body = self._json()
        method = self.path.rsplit("/", 1)[-1]
        if self.path == "/test/inbound":
            with changed:
                update_id = len(updates) + 1
                updates.append({"update_id": update_id, "message": {
                    "message_id": update_id, "chat": {"id": CHAT_ID}, "text": body["text"]}})
                changed.notify_all()
            return self._reply({"queued": update_id})
        if method == "getUpdates":
            offset = body.get("offset") or 0
            with changed:
                changed.wait_for(lambda: any(update["update_id"] >= offset for update in updates),
                                 timeout=min(body.get("timeout", 0), MAX_WAIT_SEC))
                pending = [update for update in updates if update["update_id"] >= offset]
            return self._reply({"ok": True, "result": pending})
        if method == "sendMessage":
            with changed:
                sent.append({"chat_id": body.get("chat_id"), "text": body.get("text", "")})
                message_id = len(sent)
            return self._reply({"ok": True, "result": {"message_id": message_id}})
        self._reply({"ok": False, "description": f"{method} is not faked"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    print(f"fake telegram on {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
