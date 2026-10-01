"""Operator-controlled runtime endpoint trust; never follow HTTP redirects."""

import os
import urllib.parse
import urllib.request

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_endpoint(value, trusted_hosts=()):
    parsed = urllib.parse.urlparse(value)
    allowed = LOOPBACK_HOSTS | set(trusted_hosts) | {
        host.strip().lower() for host in os.getenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", "").split(",")
        if host.strip()
    }
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("runtime endpoint port is invalid") from exc
    if (parsed.scheme != "http" or parsed.hostname not in allowed
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path != "/v1"
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("接続先は許可されたruntime hostのHTTP /v1 のみ対応")
    return parsed


class NoRuntimeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("runtime HTTP redirects are not allowed")


def runtime_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRuntimeRedirect())
