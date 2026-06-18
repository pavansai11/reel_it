# ReelMagic

**Drop a messy dump of trip photos + clips, pick a vibe, tap one button → get a finished, beat-synced, professionally-sequenced ~30s vertical reel.** No manual clip placement.

The magic isn't transitions — it's the **curation and sequencing**: deciding which moments are good and in what order/timing. Everything renders with FFmpeg on CPU (fractions of a cent/reel); a GPU is only ever optional for frame scoring. Every accept / re-roll / remove is logged as a labeled signal — the data flywheel that compounds into a moat.

> Scope is deliberately narrow (MVP): friends-trip / travel reels, vertical 1080×1920 only, 3 fixed vibes, anonymous sessions (no auth), watermark now / paywall later.

---

## Architecture

```
Next.js (3 screens)  ──HTTP──>  FastAPI  ──enqueue──>  Redis + RQ worker
   upload/processing/result        │                         │
                                    │                         ▼
                              SQLite (SQLAlchemy)      pipeline stages 1→6
                                    │                         │
                                    ▼                         ▼
                            Storage interface  ◀────  FFmpeg render (CPU)
                          (local FS  |  Cloudflare R2)
```

The pipeline (each stage is a pure function — `files/JSON in → JSON out`):

| Stage | Module | What it does |
|------:|--------|--------------|
| 1 | `s1_ingest` | Validate/probe; drop blurry photos (Laplacian var); remove pHash near-dupes |
| 2 | `s2_shots` | PySceneDetect splits videos into shots → a pool of **Moments** |
| 3 | `s3_score` | Aesthetic (CLIP/heuristic), faces+smiles, zero-shot tags, motion |
| 4 | `s4_beatmap` | Load the vibe's track's **precomputed** beat map (bpm/downbeats/energy) |
| 5 | `s5_editbrain` ⭐ | Claude builds the **Edit Decision List** (selection, order, pacing, effects); cuts snapped to the downbeat grid |
| 6 | `s6_render` | Ken Burns stills, trim/speed video, overlays, music, watermark → MP4 |

The **EDL** (`schemas.py`) is the contract between the "brain" (stage 5) and the "hands" (stage 6). Both halves depend on it.

### The edit brain runs with or without an API key
- **With `ANTHROPIC_API_KEY`:** Claude (`claude-sonnet-4-6`) produces the EDL via a forced structured tool call, validated against the EDL schema with one retry on invalid JSON.
- **Without a key:** a deterministic **heuristic brain** builds a sensible arc (establishing opener → energy build to the musical drop → wind-down) for **zero spend**. It's also the fallback if the API errors.

Either way, **every cut is snapped to a real downbeat** — we never trust the model for exact timing.

### Scoring degrades gracefully
`SCORING_BACKEND=auto` uses `open_clip` (CLIP aesthetic + zero-shot tags) and MediaPipe faces **if installed** (`requirements-ml.txt`), otherwise pure OpenCV/numpy heuristics + Haar-cascade faces. The whole product runs on a laptop and upgrades to GPU-quality scoring by installing one extra requirements file.

---

## Quick start (local)

Prereqs: **Python 3.11**, **Node 22**, **ffmpeg**, and (for queued jobs) **Redis**.

```bash
# 1. Backend: venv + deps + bundled music/beat maps
make setup                       # or see steps below
cp backend/.env.example backend/.env

# 2. Run it (three terminals, or use docker compose)
make backend                     # FastAPI on :8000
make worker                      # RQ worker (or set RUN_JOBS_INLINE=true to skip)
make frontend                    # Next.js on :3000  (cp frontend/.env.local.example .env.local)
```

Open <http://localhost:3000>, drop some photos/clips, pick a vibe, hit **Make my reel**.

<details>
<summary>Manual setup (no make)</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python scripts/generate_music.py     # synthesize bundled tracks (deterministic)
python scripts/build_beatmaps.py     # precompute beat maps with librosa
uvicorn app.main:app --reload --port 8000
```
</details>

### Try the pipeline with zero web app
Each stage has a CLI entrypoint (pure functions in → JSON/MP4 out):

```bash
cd backend
python scripts/make_test_media.py ./sample_trip   # synth a messy 15-file dump
python cli.py ingest    ./sample_trip              # stage 1 → JSON
python cli.py score     ./sample_trip              # stage 3 → JSON
python cli.py editbrain ./sample_trip --vibe energetic   # stage 5 → EDL JSON
python cli.py all       ./sample_trip --vibe energetic --out reel.mp4   # full pipeline
```

### Docker (everything at once)
```bash
ANTHROPIC_API_KEY=sk-... docker compose up --build
# frontend :3000, backend :8000, redis + worker wired up
```

---

## API

| Method | Path | Purpose |
|-------:|------|---------|
| POST | `/upload` | multipart files → asset ids (streams to storage) |
| POST | `/job` | `{ vibe, asset_ids }` → enqueue → `job_id` |
| GET | `/job/{id}/status` | `{ status, stage_progress, stage_message }` |
| GET | `/job/{id}/result` | `{ result_url, edl, … }` when done |
| POST | `/job/{id}/action` | `{ action, detail }` → logs a **UserAction** (flywheel); `rerolled` recuts |
| GET | `/health` | status + today's spend + paused flag |

---

## Cost guardrails (built in from day one)

- Per-session rate limit (`MAX_REELS_PER_SESSION_PER_DAY`).
- Hard input caps (`MAX_FILES_PER_JOB`, `MAX_UPLOAD_MB`, `MAX_VIDEO_SECONDS`).
- Frame-sampling cap (≤3 frames/moment) keeps scoring cost flat.
- **Auto-delete** media + outputs after `ASSET_TTL_HOURS` (48h) — `scripts/cleanup.py` on a cron. The flywheel data (UserAction + EDL) is kept; only blobs are purged.
- **Global kill switch:** `DAILY_SPEND_CEILING_USD` pauses new jobs when the day's spend ledger crosses the ceiling (protects against a viral spike). `0` disables it.
- CPU CLIP scoring at MVP scale; burst to serverless GPU only if throughput demands.

Tune everything in `backend/.env` (see `.env.example`).

---

## Music

The MVP ships with deterministically-synthesized, copyright-free synth beds (clear four-on-the-floor pulse + intro→build→drop→outro energy arc) so the pipeline is reproducible out of the box. Beat maps are **precomputed once** and committed (`assets/music/*.beatmap.json`); the WAVs are regenerated by `scripts/generate_music.py` (kept out of git for size).

**To ship real licensed music** (Mubert / Jamendo CC-commercial), drop your audio into `backend/assets/music/` using the `file` names in `app/pipeline/tracks.py`, then run `python scripts/build_beatmaps.py`. No code changes.

---

## Deployment

- **Frontend → Vercel:** point at `/frontend`, set `NEXT_PUBLIC_API_BASE` to your API URL.
- **Backend + worker → Railway / Render / Modal / a VPS:** build `backend/Dockerfile`; run the API and `python worker.py` against a managed Redis. Set `STORAGE_BACKEND=r2` + R2 creds; the storage interface makes local↔R2 a config swap.
- **Storage → Cloudflare R2** (S3-compatible, no egress). Schedule `scripts/cleanup.py` for the 48h purge.
- Swap SQLite → Postgres by changing `DATABASE_URL` (SQLAlchemy, no rewrites).

---

## Testing

```bash
make test        # 17 tests: EDL schema, ingest dedup/blur, on-beat edit brain, full HTTP flow
```

The API test runs the **entire pipeline inline** (upload → render → result → flywheel action) and asserts a real ≥1080×1920 MP4 lands in storage.

---

## The one test that matters (spec §10)

After the renderer works, run it on **5 real trip dumps** and ask *"would I post this without editing it?"*. Yes on ≥3/5 = you have a product. If not, the fix is almost always in **stage 5 (edit brain)** or **stage 3 (scoring)** — tune those, not the rendering. Don't add features until this passes.

---

## Repo layout

```
backend/
  app/
    main.py config.py db.py models.py storage.py queue.py guards.py
    routes/      upload.py job.py feedback.py common.py
    pipeline/    schemas.py  s1_ingest…s6_render  orchestrator.py  tracks.py  media.py
  assets/music/  bundled tracks + <track>.beatmap.json
  scripts/       generate_music.py  build_beatmaps.py  cleanup.py  make_test_media.py
  cli.py worker.py  tests/  requirements*.txt  Dockerfile
frontend/        Next.js App Router — upload / processing / result
docker-compose.yml  Makefile  README.md
```

Built to the MVP spec in `/`; phases 0–6 with acceptance criteria all wired (skeleton render → ingest/shots → scoring → beatmap+edit brain → real renderer → web app+flywheel → guardrails+deploy).
