# Kikuyu AI Music Studio

A Suno-style AI music generation platform for Gĩkũyũ language and Kenyan music traditions.

## Features

- Prompt-based song generation (Suno AI when `SUNO_API_KEY` is set, local Mũgithi engine otherwise)
- Full Suno function set via `/suno/*`: generate, lyrics, extend, cover, upload-extend/cover, add-vocals/instrumental, stems, convert-wav, timestamped lyrics, concat, mashup, persona, boost-style, status, quota
- Gĩkũyũ, Swahili, and English lyric support
- Genre presets for Mugithi, Gospel/Kĩrooko, Benga, Mwomboko, Afro-pop, and Acoustic Folk
- On-device audio synthesis engine referencing the Mugithi canon (Karplus-Strong guitar, bass, percussion, tempo switch)
- FastAPI backend with async generation jobs
- Django REST API option with account-owned songs, genre catalog, and Celery audio generation
- Next.js + Tailwind frontend with audio playback, waveform, and style references
- PostgreSQL-ready schemas for users, songs, and generation metadata

## Tech stack

- Frontend: Next.js, Tailwind CSS, Web Audio API
- Backend: FastAPI, Suno API client, local synthesis engine (NumPy), Celery, Redis
- Database: PostgreSQL / Prisma / Supabase-ready
- AI: Suno API, or local Mugithi-experience engine

## Project structure

```text
.
├── apps/
│   ├── api/
│   │   ├── main.py              # FastAPI: generation, jobs, /suno/* endpoints
│   │   ├── mugithi_engine.py    # Local synthesis engine + Mugithi reference KB
│   │   ├── suno_client.py       # Full Suno API client (all functions)
│   │   ├── manage.py
│   │   ├── requirements.txt
│   │   ├── config/
│   │   └── music/
│   │       ├── models.py
│   │       ├── serializers.py
│   │       ├── tasks.py
│   │       └── services/prompt_engine.py
│   └── web/
│       ├── app/
│       ├── components/
│       ├── package.json
│       ├── postcss.config.js
│       ├── tailwind.config.ts
│       └── tsconfig.json
├── prisma/
│   └── schema.prisma
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Quick start

### 1) Start infrastructure

```bash
docker compose up -d postgres redis
```

### 2) Start the existing FastAPI prototype

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Django REST API

The Django implementation lives beside the FastAPI prototype in `apps/api`. Copy `.env.example` to `.env` at the repository root and replace `DJANGO_SECRET_KEY` with a long random value. Install the same requirements, configure a compatible audio provider URL, then run:

```bash
cd apps/api
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_catalog
python manage.py runserver 0.0.0.0:8000
```

Run its Celery worker in a second terminal from `apps/api`:

```bash
celery -A config worker --loglevel=info
```

The DRF endpoints are `POST /api/generate/`, `GET /api/songs/?genre=mugithi`, `GET /api/songs/<id>/`, and `GET /api/genres/`. They require an authenticated Django user. Configure TLS and a production authentication backend before exposing the API. `GENERATION_BACKEND_URL` must point to a synchronous provider endpoint that accepts the task JSON and returns either audio bytes or JSON containing an `audio_url`; generated audio is limited by `GENERATION_MAX_AUDIO_BYTES`. Install `ffmpeg` on workers to populate waveform data; waveform extraction is skipped when it is unavailable. Configure Django's `STORAGES` for S3-compatible media storage in production.

The built-in lyric composer structures supplied lyrics and provides deterministic starter templates. It is not a translation or language-model service; connect a Gĩkũyũ-capable text model if fluent, prompt-specific lyrics are required.

### 3) Start the worker

```bash
cd apps/worker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
celery -A tasks worker --loglevel=info
```

### 4) Start the frontend

```bash
cd apps/web
npm install
npm run dev
```

Then open `http://localhost:3000`.

## Backend endpoint

`POST /generate-song`

Example payload:

```json
{
  "prompt": "Warm Mugithi love song with acoustic guitar and heartfelt vocals",
  "lyrics": "Nĩngũtũma wendo waku thaaiya na ngoro yaku",
  "language": "gikuyu",
  "genre": "mugithi",
  "mood": "romantic",
  "instruments": ["acoustic guitar", "bass", "djembe"],
  "duration_sec": 120
}
```

## Naming convention for language support

The app preserves diacritics for Gĩkũyũ, including characters like:

- ĩ
- ũ
- ã
- ẽ
- õ

## Next phase

This starter includes the application shell, API contract, and Celery task bridge. The next real ML phase is to integrate:

- a Gĩkũyũ G2P model
- lyric-conditioned vocal generation
- genre-specific instrument priors
- stem mixing and final audio rendering

## License

MIT
