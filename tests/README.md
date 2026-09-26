# Backend test execution

From the repository root, use the existing virtual environment:

```sh
export PATH="/opt/llm-scoring/.venv/bin:$PATH"
python -m unittest
python -m pytest -q
ruff check
```

These fixtures use isolated SQLite databases, temporary artifact directories,
and fake inference adapters. They do not require the persistent PostgreSQL DB
or a running model service.

## Restricted execution environments

Starlette TestClient uses AnyIO's blocking portal and an asyncio event loop in
another thread. The loop requires local socket-pair communication to wake up
when work is submitted. In the restricted Codex sandbox, the following minimal
probe fails with `PermissionError: [Errno 1] Operation not permitted` on `send`:

```sh
python -c 'import socket; a,b=socket.socketpair(); a.send(b"x"); print(b.recv(1)); a.close(); b.close()'
```

This can leave TestClient waiting in `BlockingPortal.start_task_soon`, including
during context-manager entry, before an API handler runs. Run the tests with
approved execution permissions that allow local socket-pair communication.
Do not disable lifespan, patch asyncio/AnyIO, or change application behavior to
work around sandbox restrictions.

Verified with Python 3.14.4, FastAPI 0.115.14, Starlette 0.46.2, HTTPX 0.27.2,
AnyIO 4.15.1 and pytest 8.3.5. No dependency change was needed.

## Review and correction fixtures

Initial Review snapshots intentionally have empty formula/figure decision maps.
Use `ReviewApiTests.ready()` to populate decisions from the owned region catalogue
before setting teacher transcriptions and marking a fixture reviewed. Iterating
the initial empty maps leaves required decisions unresolved and correctly causes
`formula_review_required` (HTTP 422).
