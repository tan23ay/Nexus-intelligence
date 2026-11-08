# Nexus Intelligence

Hourly news radar for Renewable Energy, AI Infrastructure, Semiconductors, GPUs &
Advanced Packaging (CoWoS/HBM), plus Finance, Education, Automations and Automobiles.

**Live site: https://nexus-intelligence-radar.vercel.app** (refreshed every hour)

## How it runs online (Vercel)

```
GitHub Actions (twice an hour, only if data > 50 min old) ──POST──► Vercel deploy hook
Vercel build: python3 local/fetch_news.py  ──►  site/data.json  ──►  site/ published
```

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
the GitHub secret `VERCEL_DEPLOY_HOOK`.

Note: GitHub cron is best-effort and pauses after 60 days with no repo activity. If the
site stops updating, re-enable the workflow in the Actions tab.

## Cloud version (`cloud/`)

A heavier design using Supabase (Postgres + pgvector), an OpenAI-based pipeline, and a
Next.js 14 frontend. Not deployed; needs your own Supabase/OpenAI keys. See
`cloud/supabase/schema.sql`, `cloud/pipeline/ingest.py`, and `.github/workflows/ingest.yml`
(manual-only until its secrets are set).
