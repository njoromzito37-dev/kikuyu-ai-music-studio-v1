# Kikuyu AI Music Studio

A Suno-style AI music generation platform for Gĩkũyũ language and Kenyan music traditions.

## Features

- Prompt-based song generation
- Gĩkũyũ, Swahili, and English lyric support
- Genre presets for Mugithi, Gospel/Kĩrooko, Benga, Mwomboko, Afro-pop, and Acoustic Folk
- FastAPI backend with async Celery generation jobs
- Next.js + Tailwind frontend
- PostgreSQL-ready schemas for users, songs, and generation metadata
- Audio preview and waveform-style visualizer

## Tech stack

- Frontend: Next.js, Tailwind CSS, Web Audio API
- Backend: FastAPI, Celery, Redis
- Database: PostgreSQL / Prisma / Supabase-ready
- AI: PyTorch, Hugging Face Transformers, Torchaudio, GPU inference

## Project structure

```text
.
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   └── requirements.txt
│   ├── web/
│   │   ├── app/
│   │   ├── components/
│   │   ├── package.json
│   │   ├── postcss.config.js
│   │   ├── tailwind.config.ts
│   │   └── tsconfig.json
│   └── worker/
│       ├── tasks.py
│       └── requirements.txt
├── prisma/
│   └── schema.prisma
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└──
```

## Quick start

### 1) Start infrastructure

```bash
docker compose up -d postgres redis
```

### 2) Start the backend

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

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
