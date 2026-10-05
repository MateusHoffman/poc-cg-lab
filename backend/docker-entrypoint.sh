#!/bin/sh
set -eu

python - <<'PY'
import socket
import time

targets = (("postgres", 5432), ("dynamodb-local", 8000))
for host, port in targets:
    for _ in range(40):
        try:
            with socket.create_connection((host, port), 2):
                break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit(f"{host}:{port} não respondeu")
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
