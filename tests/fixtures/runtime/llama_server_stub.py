#!/usr/bin/env python3
"""Test-only managed process implementing llama-server's wire contracts."""

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--version", action="store_true")
parser.add_argument("--list-devices", action="store_true")
parser.add_argument("-m")
parser.add_argument("--alias", default="synthetic-text-model")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8080)
args, _ = parser.parse_known_args()
if args.list_devices:
    backend = os.getenv("LLM_GRADER_STUB_BACKEND", "cpu")
    print("Available devices:")
    prefixes = {"cuda": "CUDA", "rocm": "ROCm", "vulkan": "Vulkan"}
    if backend in prefixes:
        for number in range(2):
            print(f"{prefixes[backend]}{number}: Synthetic GPU fixture (4096 MiB, 4000 MiB free)")
    raise SystemExit(0)
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
        if body.get("response_format", {}).get("json_schema", {}).get("name") == "latex_normalization":
            text = payload["text"]
            if "[latex_failure]" in text:
                self.send({"error": "synthetic normalization failure"}, 503)
                return
            normalized = text.replace("TP / (TP + FP)", r"$\frac{TP}{TP+FP}$")
            status = "safe" if normalized != text else "no_change"
            if text == "Accuracy = TP+TN / TP+FP+FN+TN":
                normalized = r"$Accuracy=\frac{TP+TN}{TP+FP+FN+TN}$"
                status = "ambiguous"
            if "[latex_numeric_change]" in text:
                normalized = text.replace("0.800", "0.8")
                status = "safe"
            if "[latex_bad_math]" in text:
                normalized = text.replace("TP / FP", r"$\frac{TP}{FP$")
                status = "safe"
            result = {"status": status, "normalized_text": normalized, "confidence": 0.95,
                      "warnings": [], "changes": []}
            self.send({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})
            return
        if body.get("response_format", {}).get("json_schema", {}).get("name") == "rubric_semantic_split":
            text = payload["text"]
            if "[split_failure]" in text:
                self.send({"error": "synthetic split failure"}, 503)
                return
            marks = list(re.finditer(r"\d+ points:", text))
            boundaries = [0] + [mark.start() for mark in marks[1:]] + [len(text)]
            split = len(marks) > 1
            result = {"candidate_id": payload["candidate_id"], "split": split, "confidence": .96,
                      "reason": "independent_criteria" if split else "single_criterion",
                      "parts": [{"start": a, "end": b} for a, b in zip(boundaries, boundaries[1:])] if split else []}
            self.send({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})
            return
        assignments = []
        for segment in payload["source_segments"]:
            text = segment["text"]
            category = "rubric" if "points" in text else (
                "alternative_answer" if "Alternative" in text else (
                    "question" if "Explain" in text or "Question " in text else "model_answer"
                )
            )
            assignments.append({"id": segment["id"], "category": category, "confidence": 0.99})
        result = {"overall_confidence": 0.99, "segments": assignments}
        self.send({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})


ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
