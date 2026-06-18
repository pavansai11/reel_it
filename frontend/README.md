# ReelMagic — frontend

Next.js (App Router) + Tailwind. Three screens: **upload → processing → result**.

## Run

```bash
cp .env.local.example .env.local     # set NEXT_PUBLIC_API_BASE (default http://localhost:8000)
npm install
npm run dev                          # http://localhost:3000
```

The backend must be running (see the root `README.md`). All API calls send the
session cookie via `credentials: 'include'`.

## Build

```bash
npm run build && npm start
```

## Structure

- `app/page.tsx` — upload: drag-drop + vibe selector + "Make my reel".
- `app/processing/[id]/page.tsx` — polls `/job/{id}/status`, friendly stage messages.
- `app/result/[id]/page.tsx` — vertical player, download, re-roll, and flywheel actions.
- `lib/api.ts` — typed API client.
- `components/` — `DropZone`, `VibeSelector`.
