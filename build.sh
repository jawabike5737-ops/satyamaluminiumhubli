#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt

# Do NOT run makemigrations on the server. Create migrations locally.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
