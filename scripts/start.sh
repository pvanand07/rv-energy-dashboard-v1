#!/bin/bash
# Start cron in background, then uvicorn in foreground
service cron start
exec uvicorn main:app --host 0.0.0.0 --port 5000 --reload
