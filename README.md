# Nexus Intelligence

Hourly news radar for Renewable Energy, AI Infrastructure, Semiconductors, GPUs &
Advanced Packaging (CoWoS/HBM), plus Finance, Education, Automations and Automobiles.

**Live site: https://nexus-intelligence-radar.netlify.app** (refreshed every hour)

## How it runs online (Netlify)

```
GitHub Actions (hourly) ──POST──► Netlify build hook
Netlify build: python3 local/fetch_news.py  ──►  site/data.json  ──►  site/ published
```

- `local/fetch_news.py` pulls ~19 RSS feeds (Python standard library only, no API keys),
  classifies stories with keyword rules, scores impact, detects funding deals, dedups,
  and keeps a rolling 10-day history.
- `site/index.html` is the dashboard. Reads and bookmarks are stored in each browser.
- Edit the `SOURCES` list in `local/fetch_news.py` to add or remove feeds; push to redeploy.

**One-time setup:** connect this repo in Netlify (build settings come from `netlify.toml`),
then create a build hook and save its URL as the GitHub secret `NETLIFY_BUILD_HOOK`.

Note: GitHub pauses scheduled workflows after 60 days with no repo activity. If the site
stops updating, re-enable the workflow in the Actions tab.

## Cloud version (`cloud/`)

A heavier design using Supabase (Postgres + pgvector), an OpenAI-based pipeline, and a
Next.js 14 frontend. Not deployed; needs your own Supabase/OpenAI keys. See
`cloud/supabase/schema.sql`, `cloud/pipeline/ingest.py`, and `.github/workflows/ingest.yml`
(manual-only until its secrets are set).
