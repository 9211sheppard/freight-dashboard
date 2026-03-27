#!/bin/bash
pip install -r requirements-azure.txt --quiet
gunicorn wsgi:app --workers 2 --bind 0.0.0.0:8000 --timeout 120
