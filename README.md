# Viral Shorts AI

Turn long videos into scroll-stopping vertical Shorts automatically.

Upload a video (a podcast, a vlog, a courtroom recording — anything with people
talking), and Viral Shorts AI finds the most engaging moments, cuts them into
9:16 vertical clips, adds punchy karaoke-style captions, and hands you files
ready to post on YouTube Shorts, TikTok, or Instagram Reels.

No video-editing skills needed. If you can upload a file and tap a button, you
can use this app.

---

## Table of contents

- [What this app does](#what-this-app-does)
- [How it works (pipeline stages)](#how-it-works-pipeline-stages)
- [Requirements](#requirements)
- [Quick local dev](#quick-local-dev)
- [GPU server setup, step by step](#gpu-server-setup-step-by-step)
- [Domain + HTTPS](#domain--https)
- [Environment variables](#environment-variables)
- [Using it from Android Chrome](#using-it-from-android-chrome)
- [Where the AI models live](#where-the-ai-models-live)
- [Expected GPU requirements](#expected-gpu-requirements)
- [Scaling from 1 user to many](#scaling-from-1-user-to-many)
- [Troubleshooting](#troubleshooting)
- [Storage cleanup](#storage-cleanup)
- [Security notes](#security-notes)

---

## What this app does

**In one sentence:** you give it a long horizontal video, it gives you back
several short vertical videos with captions, each one picked to grab attention.

Concretely:

1. **Upload** a video from your phone or computer (MP4/MOV, up to the
   configured size limit).
2. **Pick** how many Shorts you want and how long each should be
   (e.g. 3 clips of 30–60 seconds).
3. **Wait** while the AI watches the whole video, listens to every word, and
   scores every possible moment.
4. **Download** the finished vertical (9:16) clips with animated word-by-word
   captions, ready to upload to YouTube Shorts / TikTok / Reels.

What makes a moment "good"? The AI scores each candidate clip on 7 signals —
questions asked, emotional intensity, audio energy, strong hooks, and more —
then picks the top clips while making sure they don't all come from the same
30 seconds of your video.

---

## How it works (pipeline stages)

Every video goes through the same pipeline. Understanding the stages helps when
something goes wrong (see [Troubleshooting](#troubleshooting)).

```
Upload → Transcribe → Energy analysis → Candidate generation
       → Scoring → Top-clip selection → Face tracking & framing
       → Captions → Render 9:16 → Done (download links)
```

| # | Stage | What happens | Code |
|---|-------|--------------|------|
| 1 | **Upload** | File is validated (type + size), stored in S3-compatible storage, a job row is created in the database. | `backend/app/main.py` → `POST /api/upload/init` |
| 2 | **Transcribe** | faster-whisper (AI speech-to-text) turns audio into word-level timestamps: every word with start/end times. | worker |
| 3 | **Energy analysis** | Audio loudness (RMS energy) is sampled over time; loud/emotional stretches get flagged. | worker |
| 4 | **Candidate generation** | The transcript is sliced into candidate windows of your requested durations. Cuts always snap to sentence boundaries — never mid-word. | `worker/pipeline/viral.py` → `generate_candidates()` |
| 5 | **Scoring** | Each candidate gets a 0–100 score from 7 weighted components (see `WEIGHTS`). Questions, emotion, energy spikes, and hooks score highest. | `worker/pipeline/viral.py` → `score_candidate()` |
| 6 | **Top-clip selection** | The best `n` clips are chosen with a max-overlap rule (default 30%) so clips don't repeat the same moment. | `worker/pipeline/viral.py` → `select_top_clips()` |
| 7 | **Face tracking & framing** | Faces are detected per frame and the 9:16 crop follows the speaker, so the vertical video keeps the right person in frame. | worker |
| 8 | **Captions** | Word timings become an ASS subtitle file with karaoke highlighting (`{\k}` tags), Hormozi-style: 1–2 punchy lines, key words emphasized. | `worker/pipeline/captions.py` → `build_ass()` |
| 9 | **Render** | ffmpeg burns captions into a 9:16 MP4 (H.264) at up to 4K, uploads it to storage, and the job is marked complete. | worker |

Job progress is visible at `GET /api/jobs/{job_id}/progress`; finished clips
download from `GET /api/clips/{clip_id}/download`.

---

## Requirements

### For running it (production / GPU server)

- **NVIDIA GPU** — transcription and face tracking run on CUDA. See
  [Expected GPU requirements](#expected-gpu-requirements) for how much VRAM
  each model needs.
- **Docker** (Engine 24+) **and Docker Compose v2**.
- **NVIDIA Container Toolkit** so Docker containers can see the GPU
  (`nvidia-ctk`).
- **A domain name** (e.g. `https://example.com`) with DNS you control, for
  HTTPS. Any registrar works.
- **Disk:** ~30 GB free (models ~10 GB, plus headroom for uploads/renders).
- **RAM:** 16 GB recommended on the host.

### For local development (your laptop)

- Docker + Docker Compose only. Run with `CPU_ONLY=1` (see below) — no GPU
  needed, just slower. Good for testing the API, the UI, and the pipeline
  plumbing; not for real transcription speed.

---

## Quick local dev

```bash
# from the repo root
./scripts/dev.sh            # GPU build (default)
CPU_ONLY=1 ./scripts/dev.sh # CPU-only build, no NVIDIA GPU needed
```

The script:

1. Checks that `docker` and `docker compose` exist (and tells you how to
   install them if not).
2. Copies `.env.example` → `.env` if you don't have one yet.
3. Runs `docker compose up --build -d` (with `--profile cpu` for the worker
   when `CPU_ONLY=1`).

When it's up:

- API: http://localhost:8000
- Interactive API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health
- Frontend: http://localhost:3000

Useful commands:

```bash
docker compose logs -f          # follow all logs
docker compose logs -f worker   # just the pipeline worker
docker compose down             # stop everything
```

Run the test-suite (needs the backend/worker code present):

```bash
pip install -r tests/requirements.txt
pytest tests/ -v
```

> **Note for CPU-only mode:** the first transcription downloads the whisper
> model and runs on CPU — expect roughly 0.3–1× realtime (a 10-minute video
> can take 10–30 minutes). This is fine for smoke tests.

---

## GPU server setup, step by step

These steps assume a fresh Ubuntu 22.04/24.04 server with an NVIDIA GPU
(any cloud provider: Lambda Labs, RunPod, Vast.ai, AWS `g5.xlarge`, etc.).

### 1. Create the server

- Pick an image with NVIDIA drivers, or plain Ubuntu and install drivers
  yourself (`sudo ubuntu-drivers autoinstall`, then reboot).
- Open ports **80** and **443** (HTTP/HTTPS) in the firewall/security group.
  Port 22 for your SSH as usual.
- Verify the GPU is visible: `nvidia-smi` should list your card.

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in so the group applies
docker --version
docker compose version
```

### 3. Install the NVIDIA Container Toolkit

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify Docker can see the GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 4. Clone the repo and configure

```bash
git clone <your-repo-url> viral-shorts-ai
cd viral-shorts-ai
cp .env.example .env
nano .env   # fill in everything in the Environment variables table below
```

### 5. Pre-download the AI model (recommended)

```bash
pip install faster-whisper          # or do this inside the worker container
WHISPER_MODEL=large-v3 python scripts/download_models.py
```

This pulls the weights from HuggingFace once, so the first real job isn't
slow. (Without this step the download still happens automatically on first
use — it's just slower then.)

### 6. Build and start

```bash
docker compose up --build -d
docker compose logs -f worker   # watch the worker come up; Ctrl+C to detach
```

### 7. Check health

```bash
curl https://example.com/api/health        # after DNS+HTTPS below, or
curl http://<server-ip>:8000/api/health    # direct, pre-domain
```

You should get HTTP 200. Now point your domain at the server
([next section](#domain--https)) and open the frontend in Chrome.

---

## Domain + HTTPS

You need a domain (we'll use `https://example.com` as the placeholder —
replace it with your real domain everywhere).

### 1. DNS A record

In your registrar's DNS panel, add:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `@` | `<your-server-ip>` | 300 |
| A | `www` | `<your-server-ip>` | 300 |

Wait for propagation (`dig +short example.com` should return your IP;
can take minutes to hours).

### 2. Option A — Let's Encrypt with certbot + nginx (recommended)

The repo ships an nginx reverse-proxy config in `nginx/`.

```bash
sudo apt-get install -y certbot python3-certbot-nginx
# point nginx at the compose frontend/backend first (see nginx/nginx.conf),
sudo certbot --nginx -d example.com -d www.example.com
```

Certbot fetches the certificate, rewrites the nginx config for HTTPS, and
sets up auto-renewal. Verify renewal works:

```bash
sudo certbot renew --dry-run
```

### 3. Option B — Caddy (simpler alternative)

If you'd rather not touch nginx configs, Caddy gets certificates automatically:

```
# Caddyfile
example.com {
    reverse_proxy localhost:3000   # frontend
}
example.com/api/* {
    reverse_proxy localhost:8000   # backend API
}
```

```bash
sudo apt-get install -y caddy
# place the Caddyfile at /etc/caddy/Caddyfile, then:
sudo systemctl reload caddy
```

Caddy obtains and renews the Let's Encrypt certificate on its own — no
certbot needed.

---

## Environment variables

Copy `.env.example` to `.env` and set these. **Never commit `.env`.**

| Variable | Example | Required | What it does |
|----------|---------|----------|--------------|
| `ENVIRONMENT` | `production` | yes | `production` / `staging` / `development` |
| `DATABASE_URL` | `postgresql://user:pass@db:5432/shorts` | yes | Postgres connection string. Tests override with sqlite. |
| `REDIS_URL` | `redis://redis:6379/0` | yes | Celery broker + result backend |
| `S3_ENDPOINT_URL` | `https://s3.amazonaws.com` | yes | Any S3-compatible endpoint (AWS S3, MinIO, R2…) |
| `S3_BUCKET` | `viral-shorts-prod` | yes | Bucket for uploads and rendered clips |
| `AWS_ACCESS_KEY_ID` | `AKIA…` | yes | Storage credentials |
| `AWS_SECRET_ACCESS_KEY` | `…` | yes | Storage credentials |
| `WHISPER_MODEL` | `large-v3` | no | faster-whisper model: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `MAX_UPLOAD_MB` | `2048` | no | Max upload size in MB (default 2048) |
| `ALLOWED_MIME_TYPES` | `video/mp4,video/quicktime` | no | Comma-separated allow-list for uploads |
| `JWT_SECRET` | `<long random string>` | yes | Signs auth tokens — generate with `openssl rand -hex 32` |
| `FRONTEND_URL` | `https://example.com` | yes | Used for CORS + share links |

Test-only overrides (set automatically by `tests/conftest.py`, you don't
need to set these yourself):

| Variable | Test value |
|----------|------------|
| `DATABASE_URL` | `sqlite:////tmp/test_viral_shorts.db` |
| `REDIS_URL` | `redis://localhost:6379/15` |
| `CELERY_BROKER_URL` | `memory://` |

---

## Using it from Android Chrome

The frontend is a PWA (installable web app) — no Play Store needed.

1. **Install:** open `https://example.com` in Chrome → menu (⋮) →
   **Install app** / **Add to Home screen**. It now opens full-screen like a
   native app.
2. **Upload:** tap *New Shorts* → pick a video from your gallery (or record
   one). Uploads resume if your connection drops.
3. **Configure:** choose the language spoken in the video, how many clips
   you want, and clip lengths (e.g. 3 × 30–60s).
4. **Generate:** tap *Generate*. You can close the app — processing happens
   on the server. Progress is shown per job.
5. **Download:** when done, each clip has a **Download** button (MP4, H.264 —
   plays on every Android phone) and a **Share** button that opens the
   Android share sheet straight into YouTube / TikTok / Instagram.

Tips:

- Upload on Wi-Fi for large files; a 10-minute 1080p video is ~500 MB–1 GB.
- Clips render in 9:16 automatically — film horizontal (16:9) source for the
  best face-tracking results.
- If captions look wrong (wrong language), re-run the job with the correct
  language selected — transcription follows that setting.

---

## Where the AI models live

| Model | Used for | Location |
|-------|----------|----------|
| faster-whisper (`large-v3` default) | Speech-to-text with word timestamps | `~/.cache/huggingface` inside the worker container (a named Docker volume in compose, so it survives restarts) |
| Face detection/tracking | Keeping the speaker framed in 9:16 | Bundled with the worker image |
| PyTorch + CUDA | GPU acceleration for the above | Inside the worker image (`torch` with CUDA 12.x) |

To warm the cache during build/deploy instead of on first use:

```bash
WHISPER_MODEL=large-v3 python scripts/download_models.py
```

To switch models later, change `WHISPER_MODEL` in `.env` and restart the
worker — the new weights download once, then are cached.

---

## Expected GPU requirements

faster-whisper VRAM is the binding constraint. Pick the model your card can
hold (figures are approximate, fp16):

| Model | VRAM needed | Quality | Notes |
|-------|-------------|---------|-------|
| `tiny` | ~1 GB | Low | Smoke tests only |
| `base` | ~1 GB | Okay | Quick drafts |
| `small` | ~2 GB | Good | Budget GPUs |
| `medium` | ~5 GB | Very good | Sweet spot for most cards |
| `large-v3` | **~10 GB** | Best | Recommended for production |

Face tracking adds ~1–2 GB on top during rendering.

**Rule of thumb:**

- 8 GB card (e.g. RTX 3060) → `small` or `medium`
- 12 GB card (e.g. RTX 3060 12GB, 4070) → `medium`, or `large-v3` if nothing
  else runs alongside
- 16 GB+ (e.g. RTX 4080, A10) → `large-v3` comfortably
- 24 GB+ (e.g. RTX 4090, L4, A100) → `large-v3` + headroom for concurrent jobs

Set `WHISPER_MODEL` in `.env` accordingly. If the worker crashes with CUDA
out-of-memory, drop one model size and restart.

---

## Scaling from 1 user to many

One server handles the first users fine. When jobs start queueing:

1. **More workers (easiest win).** The pipeline is a Celery queue — run more
   worker containers. On one GPU box:
   ```bash
   docker compose up --scale worker=2 -d   # needs enough VRAM for 2× models
   ```
   On multiple GPU boxes: point every worker at the same `REDIS_URL` and
   `S3_BUCKET`; they pull jobs from the shared queue automatically.
2. **Concurrency per worker.** Celery `-c` (concurrency) controls parallel
   tasks per container. GPU tasks are VRAM-bound — usually `-c 1` per GPU
   for transcription, higher for pure-CPU steps (caption burn-in).
3. **Separate the queues.** Route transcription (GPU-heavy) and rendering
   (CPU/ffmpeg) to different Celery queues so a render backlog never blocks
   transcription.
4. **Storage.** Move from single-disk MinIO to real S3/R2 and enable
   lifecycle rules (auto-delete raw uploads after N days — see
   [Storage cleanup](#storage-cleanup)).
5. **Database.** Postgres handles thousands of jobs easily; add read
   replicas / connection pooling (PgBouncer) only when the API itself is the
   bottleneck.
6. **Frontend/API.** The API is stateless — scale it horizontally behind
   nginx/Caddy with no shared state beyond Postgres/Redis/S3.

Rough capacity planning: one `large-v3` worker transcribes ~3–6× realtime
(10-min video in ~2–3 min) plus render time. Size workers so p95 queue wait
stays under your target.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `docker: command not found` | Docker not installed | See [step 2](#2-install-docker) |
| `could not select device driver "" with capabilities: [[gpu]]` | NVIDIA Container Toolkit missing/misconfigured | Re-run [step 3](#3-install-the-nvidia-container-toolkit), then `sudo systemctl restart docker` |
| Worker crashes: `CUDA out of memory` | Model too big for the card | Lower `WHISPER_MODEL` (e.g. `large-v3` → `medium`), restart worker |
| First job is very slow, then fast | Model downloading on first use | Pre-warm with `scripts/download_models.py` |
| **"Video processing failed during face tracking"** | Face detection crashed on this video — common causes: very low resolution (<480p), extreme motion blur, no detectable face for long stretches, or a corrupt/odd codec file | 1) Re-encode the source: `ffmpeg -i in.mp4 -vf scale=1280:-2 -c:v libx264 -pix_fmt yuv420p fixed.mp4` and re-upload. 2) If it persists on a clean file, check worker logs (`docker compose logs worker`) for the exact frame/traceback and file an issue with the video's `ffprobe` output. 3) As a stopgap, jobs can fall back to center-crop framing if face tracking is disabled for that job. |
| Upload fails immediately | File over `MAX_UPLOAD_MB` or MIME not in `ALLOWED_MIME_TYPES` | Check `.env` limits; re-export as MP4 (H.264) |
| `POST /api/jobs` → 422 | Invalid `language`, `num_shorts` out of range, or bad `durations` | See [test_api.py](tests/test_api.py) for the accepted shapes |
| Captions in the wrong language | Wrong language selected at job creation | Re-create the job with the correct `language` |
| `https://example.com` shows a cert warning | Certbot didn't complete or DNS hasn't propagated | `dig +short example.com`, then re-run `sudo certbot --nginx -d example.com -d www.example.com` |
| Clips all come from the same part of the video | `max_overlap` too high or too few candidates | Lower `max_overlap` (default 0.3) / request more candidate durations |
| DB connection errors in tests | Real `DATABASE_URL` leaking into tests | `tests/conftest.py` force-sets sqlite — make sure you're running `pytest` from the repo root so conftest loads |

Reading logs:

```bash
docker compose logs -f worker    # pipeline errors live here
docker compose logs -f backend   # API errors live here
docker compose ps                # are all services actually up?
```

---

## Storage cleanup

Video files pile up fast. Policy used here:

- **Raw uploads:** safe to delete after the job completes (or after N days).
- **Rendered clips:** keep as long as users download them; age them out after
  N days (default 30).
- **Database rows:** prune `jobs`/`clips` older than N days.

Run it (dry run by default — lists what *would* be deleted):

```bash
./scripts/cleanup.sh 30              # what would be deleted (older than 30d)
DRY_RUN=0 ./scripts/cleanup.sh 30    # actually delete
```

Requirements: `S3_BUCKET` and AWS credentials in the environment. Without
them the script explains what it would clean and exits — it never guesses.

Prefer S3 lifecycle rules for large buckets (cheaper and automatic):

```json
{
  "Rules": [{
    "ID": "expire-old-uploads",
    "Prefix": "uploads/raw/",
    "Status": "Enabled",
    "Expiration": { "Days": 30 }
  }]
}
```

Docker volumes are **never** pruned automatically by the script — inspect with
`docker system df -v` and remove volumes by name yourself.

---

## Security notes

- **API keys never go in the frontend.** The browser talks to our backend;
  the backend holds the storage credentials. There is no key to steal from
  the client bundle because none is shipped in it.
- **`.env` is secret.** It holds `AWS_SECRET_ACCESS_KEY`, `JWT_SECRET`, and
  the database password. Never commit it, never paste it into chat/logs.
  Rotate `JWT_SECRET` with `openssl rand -hex 32` if it's ever exposed.
- **Upload validation is server-side.** `POST /api/upload/init` enforces the
  MIME allow-list and size cap — client-side checks are UX only, the server
  re-validates everything (see [test_upload_validation.py](tests/test_upload_validation.py)).
- **Signed URLs, short-lived.** Downloads/uploads use presigned S3 URLs that
  expire; the bucket itself is private.
- **Keep images updated.** Rebuild (`docker compose up --build`) regularly to
  pick up base-image security patches; pin versions in Dockerfiles.
- **Backups.** Snapshot Postgres (`pg_dump` on a cron) and enable bucket
  versioning for anything you can't regenerate.

---

*Placeholder domain used throughout this README: `https://example.com` —
replace with your real domain.*
