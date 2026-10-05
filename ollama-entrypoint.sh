#!/bin/sh
set -eu

ollama serve &
pid=$!
trap 'kill "$pid"' TERM INT

until ollama list >/dev/null 2>&1; do
  sleep 1
done

ollama pull llama3.1:8b
wait "$pid"
