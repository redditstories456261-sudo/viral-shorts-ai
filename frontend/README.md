# Viral Shorts AI — Frontend

React + TypeScript + Vite + Tailwind CSS, mobile-first PWA targeting Android Chrome.

## Setup

```sh
npm install
```

## Configuration

The backend base URL comes **only** from the build-time environment variable:

```sh
VITE_API_URL=https://api.example.com npm run build
```

No API keys or secrets are used anywhere in this frontend.

## Scripts

- `npm run dev` — local development server
- `npm run build` — type-check (`tsc`) then production build
- `npm run preview` — preview the production build

## How it works

1. **Upload** (`src/components/UploadCard.tsx`): picks a video, hashes it with
   incremental SHA-256 (`src/lib/sha256.ts`), then uploads it in 5 MB chunks via
   `PUT /api/upload/{id}/chunk` with `Content-Range` headers. Pause/resume and
   per-chunk retry (3 attempts, re-syncs with the server's `received_bytes`)
   are built into `ResumableUploader` (`src/lib/upload.ts`). Completion sends
   the hex digest as the `X-Content-Checksum` header.
2. **Configure** (`src/components/JobForm.tsx`): language (auto/en/hi/ur),
   number of shorts (1–20 stepper), min/max clip duration (30/45/60/75/90,
   min ≤ max enforced).
3. **Processing** (`src/components/ProgressView.tsx`): polls
   `GET /api/jobs/{id}/progress` every 2 s and renders the ten pipeline stages
   with the current one highlighted plus an overall progress bar.
4. **Results** (`src/components/ClipCard.tsx`): one card per clip with a 9:16
   `<video>` preview (the download endpoint 302-redirects to the file),
   title, hook, virality score, and duration. Preview scrolls to and plays the
   clip; Download uses an anchor with the `download` attribute; Share uses
   `navigator.share` with a real `File` when supported and falls back to
   downloading.

## PWA

`vite-plugin-pwa` generates the manifest (`Viral Shorts AI`, standalone,
`#000000` theme) and a service worker that precaches the static UI shell only.
API responses and video files are never cached. Icons live in
`public/icons/`.
