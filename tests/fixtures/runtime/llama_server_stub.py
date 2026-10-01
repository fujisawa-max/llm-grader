#!/usr/bin/env python3
"""Test-only managed process implementing llama-server's wire contracts."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--version", action="store_true")
parser.add_argument("-m")
parser.add_argument("--alias", default="synthetic-text-model")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8080)
args, _ = parser.parse_known_args()
if args.version:
    print("synthetic llama-server fixture (no model inference)")
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    def send(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send({"status": "ok"})
        elif self.path == "/v1/models":
            self.send({"data": [{"id": args.alias}]})
        elif self.path == "/props":
            self.send({"modalities": {"vision": False}})
        else:
            self.send({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or body.get("model") != args.alias:
            self.send({"error": "invalid endpoint or model"}, 400)
            return
        payload = json.loads(body["messages"][-1]["content"])
        assignments = []
        for segment in payload["source_segments"]:
            text = segment["text"]
            category = "rubric" if "points" in text else (
                "alternative_answer" if "Alternative" in text else (
                    "question" if "Explain" in text else "model_answer"
                )
            )
            assignments.append({"id": segment["id"], "category": category, "confidence": 0.99})
        result = {"overall_confidence": 0.99, "segments": assignments}
        self.send({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})


ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
