# AeroTrack

A Django-based airline operations and passenger experience demo project.

## Highlights
- Human-friendly flight search and detail pages
- Live route map with animated aircraft movement
- AI-supported chat triage for quick support questions
- Automatic escalation to support representatives for complex issues
- Branded admin dashboard with operational metrics and quick actions

## Tech Stack
- Python 3.9+
- Django 4.2
- PostgreSQL (production)
- SQLite (local fallback)
- Gunicorn + WhiteNoise (production serving)

## Quick Start (One Command)
Run this from the project root:

```bash
./run_local.sh
```

This script will:
1. Create a `.venv` if missing
2. Install dependencies from `requirements.txt`
3. Run migrations
4. Start Django on `http://127.0.0.1:8000`

## Manual Local Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Environment Variables
Use `.env.example` as a reference.

Required for production:
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DATABASE_URL`

## Deploy on Render
This repo includes `render.yaml` and `Procfile`.

### Option A: Blueprint Deploy (Recommended)
1. Push repo to GitHub.
2. In Render, click `New +` -> `Blueprint`.
3. Select the repo.
4. Render provisions both web service + PostgreSQL from `render.yaml`.

### Option B: Manual Web Service
1. Create a new `Web Service`.
2. Build command:
   ```bash
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
   ```
3. Start command:
   ```bash
   gunicorn config.wsgi:application
   ```
4. Attach a PostgreSQL database.
5. Set env vars (`SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`).

## Post-Deploy
Create an admin user from your Render shell:

```bash
python manage.py createsuperuser
```

## Common Issues
- `Could not detect static files` from Wrangler:
  This project is Django backend, not Cloudflare static Workers/Pages. Deploy with Render/Railway/Fly.io.

- `ModuleNotFoundError` for dependencies:
  Re-run `pip install -r requirements.txt` in your active virtualenv.

- DB connection errors locally:
  Ensure PostgreSQL is running if using `DATABASE_URL`, or remove it to use SQLite fallback.
