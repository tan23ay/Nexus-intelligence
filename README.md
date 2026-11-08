# Nexus Intelligence

Hourly news radar for Renewable Energy, AI Infrastructure, Semiconductors, GPUs &
Advanced Packaging (CoWoS/HBM), plus Finance, Education, Automations and Automobiles.

**Live site: https://nexus-intelligence-radar.vercel.app** (refreshed every hour)

## How it runs online (Vercel)

```
Visitor ──► /api/news (Vercel Python function, CDN-cached 15 min) ──► live RSS + baked history
GitHub Actions (backup, twice an hour) ──POST──► Vercel deploy hook ──► rebuilds data.json
```

- `api/news.py` fetches the feeds on demand, so the site stays fresh without any
  scheduler. Vercel's CDN caches the result for 15 minutes and refreshes it in the
  background, so feeds are hit at most ~4 times an hour however many people visit.
- Each build bakes a 31-day history into `site/data.json`; the function merges live
  stories on top of it. The page falls back to `data.json` if the function fails.

- `local/fetch_news.py` pulls ~19 RSS feeds (Python standard library only, no API keys),
  classifies stories with keyword rules, scores impact, detects funding deals, dedups,
  and keeps a rolling 31-day history.
- `site/index.html` is the dashboard. Reads and bookmarks are stored in each browser.
- Click any topic, sector or source on a card for **Related news** over the past week or
  past month. The view has a shareable link (e.g. `/#topic=sub:hbm_memory&range=month`)
  and a matching Google News search.
- Edit the `SOURCES` list in `local/fetch_news.py` to add or remove feeds; push to redeploy.

**One-time setup:** import this repo in Vercel (build settings come from `vercel.json`),
then create a deploy hook for `main` (Settings → Git → Deploy Hooks) and save its URL as
the GitHub secret `VERCEL_DEPLOY_HOOK`. Optionally also add it in Vercel as the
environment variable `DEPLOY_HOOK`: the function then triggers a rebuild itself when the
baked history is over 3 hours old.

GitHub cron is best-effort (runs can be late, skipped, or paused after 60 days without
repo activity). That only affects how often history is baked in; live stories come from
`/api/news` regardless.

## Cloud version (`cloud/`)

A heavier design using Supabase (Postgres + pgvector), an OpenAI-based pipeline, and a
Next.js 14 frontend. Not deployed; needs your own Supabase/OpenAI keys. See
`cloud/supabase/schema.sql`, `cloud/pipeline/ingest.py`, and `.github/workflows/ingest.yml`
(manual-only until its secrets are set).
