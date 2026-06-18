#!/bin/bash
cd "$(dirname "$0")/backend"
uvicorn main:app --reload --port 8000
