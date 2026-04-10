#!/usr/bin/env bash

pip install -r requirements.txt

python manage.py makemigrations core
python manage.py migrate --fake-initial
python manage.py migrate

python manage.py collectstatic --noinput
