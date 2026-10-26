#!/bin/bash
# Azure App Service (Linux) startup command. ONE worker on purpose: the simulator runs inside the
# web process and SQLite allows a single writer. Threads handle concurrent dashboard requests.
exec gunicorn --bind=0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120 app:app
