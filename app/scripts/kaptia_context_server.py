"""Loopback-only context helper for the Kaptia scratch model.

This service never calls an external model or downloads model weights.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from chat import acceptable_generated_text, build_generator, load_language_engine  # noqa: E402

HOST = "127.0.0.1"
PORT = 43871
MAX_BODY = 48 * 1024
MAX_SELECTION_CHARS = 12000


class Handler(BaseHTTPRequestHandler):
    server_version = "KaptiaContext/0.1"

    def log_message(self, fmt, *args):
        # Do not log source code or user prompts.
        print("[Kaptia context] " + (fmt % args))

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/health":
            self._send(404, {"error": "not_found"})
            return
        self._send(200, {"ok": True, "engine": "kaptia-scratch-only"})

    def do_POST(self):
        if self.path != "/ask":
            self._send(404, {"error": "not_found"})
            return
        if self.client_address[0] != "127.0.0.1":
            self._send(403, {"error": "loopback_only"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > MAX_BODY:
            self._send(413, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._send(400, {"error": "invalid_request"})
            return

        question = str(payload.get("question", "請解釋這段程式碼的用途與執行流程。")).strip()[:500]
        selection = str(payload.get("selection", ""))[:MAX_SELECTION_CHARS]
        before = str(payload.get("before", ""))[-2500:]
        after = str(payload.get("after", ""))[:2500]
        file_name = Path(str(payload.get("fileName", "目前檔案"))).name[:180]
        if not selection.strip():
            self._send(400, {"error": "empty_selection", "message": "請先選取一段程式碼。"})
            return

        # ByteTokenizer consumes one token per UTF-8 byte. Reserve room for the
        # question and selected code first; nearby context is only secondary.
        context_length = self.server.model.config.context_length
        question_bytes = question.encode("utf-8")[:72]
        question = question_bytes.decode("utf-8", errors="ignore")
        fixed = f"檔案:{file_name[:40]}\n問:{question}\n選取程式碼:\n"
        fixed_bytes = fixed.encode("utf-8")
        available = max(24, context_length - len(fixed_bytes) - 20)
        selection_bytes = selection.encode("utf-8")[:available]
        selection = selection_bytes.decode("utf-8", errors="ignore")
        # Keep only a small context tail if there is still room after the selected code.
        remaining = max(0, context_length - len((fixed + selection).encode("utf-8")) - 24)
        context = ""
        if remaining and before:
            context = ("\n前文:" + before[-remaining:]) if before else ""
        prompt_text = fixed + selection + context + "\n請用繁體中文解釋。"
        try:
            answer = self.server.generate([{"role": "user", "content": prompt_text}],
                                          max_new_tokens=min(160, max(32, context_length // 2)),
                                          temperature=0.25)
        except Exception as exc:
            self._send(500, {"error": "generation_failed", "message": type(exc).__name__})
            return
        if not acceptable_generated_text(answer):
            self._send(200, {
                "ok": False,
                "status": "model_not_ready",
                "answer": "目前的 Kaptia 從零訓練模型尚無法可靠解釋這段程式碼。請繼續使用合法語料訓練後再試；本功能不會改用任何成品模型。",
                "model": "kaptia-scratch-only",
            })
            return
        self._send(200, {
            "ok": True,
            "status": "experimental",
            "answer": answer,
            "warning": "實驗性 scratch 模型輸出，可能錯誤；請勿未經檢查就套用程式碼修改。",
            "model": "kaptia-scratch-only",
        })


def main():
    tokenizer, model = load_language_engine()
    generate = build_generator(tokenizer, model)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.tokenizer = tokenizer
    server.model = model
    server.generate = generate
    print(f"[Kaptia context] Listening on http://{HOST}:{PORT} (loopback only)")
    server.serve_forever()


if __name__ == "__main__":
    main()
