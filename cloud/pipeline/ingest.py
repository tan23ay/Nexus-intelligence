"""
Nexus Intelligence — hourly ingestion pipeline.

Reads active sources from `rss_sources`, collects candidate articles (RSS or
homepage scrape), dedups by URL hash and embedding similarity, enriches with an
LLM (category, hardware subcategories, impact score, funding extraction), and
writes to Supabase. Run hourly from GitHub Actions (.github/workflows/ingest.yml).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from supabase import Client, create_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ingest")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
EMBED_MODEL = "text-embedding-3-small"   # 1536 dims, matches vector(1536)
MAX_NEW_PER_SOURCE = int(os.environ.get("MAX_NEW_PER_SOURCE", "15"))
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.92"))
USER_AGENT = "NexusIntelligenceBot/1.0 (+news aggregator)"

CATEGORIES = {
    "renewable_energy", "ai_infrastructure", "semiconductors", "gpu_production",
    "finance", "education", "automations", "automobiles",
}
SUBCATEGORIES = {
    "advanced_packaging_cowos", "hbm_memory", "gpu_accelerators",
    "wafer_fabs", "lithography", "custom_asics",
}
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid"}

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai = OpenAI(api_key=OPENAI_API_KEY)
http = requests.Session()
http.headers["User-Agent"] = USER_AGENT


# ----------------------------------------------------------------------------- helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Strip fragments/tracking params so the same story hashes identically."""
    p = urlparse(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING_PARAMS])
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def fetch(url: str) -> str | None:
    try:
        r = http.get(url, timeout=15)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        log.warning("fetch failed %s: %s", url, e)
        return None


def extract_body(html: str) -> tuple[str, str | None]:
    """Return (plain text, published ISO date if found) from an article page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = "\n".join(p.get_text(" ", strip=True) for p in root.find_all("p"))
    published = None
    meta = soup.find("meta", attrs={"property": "article:published_time"}) or \
        soup.find("meta", attrs={"name": "pubdate"})
    if meta and meta.get("content"):
        published = meta["content"]
    return text, published


# ----------------------------------------------------------------------------- collection
def candidates_from_rss(source: dict) -> list[dict]:
    feed = feedparser.parse(source["url"], agent=USER_AGENT)
    out = []
    for e in feed.entries:
        link = e.get("link")
        if not link:
            continue
        published = None
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        out.append({
            "url": link,
            "title": e.get("title", "").strip(),
            "author": e.get("author"),
            "published_at": published,
            "rss_summary": BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True),
        })
    return out


def candidates_from_scrape(source: dict) -> list[dict]:
    html = fetch(source["url"])
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(source["url"]).netloc.replace("www.", "")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        url = urljoin(source["url"], a["href"])   # handle relative links
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            continue
        if base_host not in p.netloc:              # skip ads / social / off-site links
            continue
        if len(title) < 25 or len(p.path.strip("/").split("/")[-1]) < 8:
            continue                                # nav items, category pages
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": title})
    return out


# ----------------------------------------------------------------------------- enrichment
ANALYSIS_PROMPT = """You are an analyst for a tech/energy/semiconductor intelligence feed.
Analyze the article below and respond with JSON only.

Title: {title}
Source: {source}
Text:
{text}

Rules:
- primary_category: exactly one of {categories}.
  semiconductors = foundries, wafer fabs, lithography, chip design/IP, fab policy.
  gpu_production = GPUs/AI accelerators, HBM, CoWoS/advanced packaging, accelerator supply chain.
- secondary_categories: zero or more other categories from the same list.
- subcategories: zero or more of {subcategories} (hardware stories only).
- impact_score 1.0–10.0. Reserve >= 8.5 for genuine breakthroughs, new fab lines coming online,
  major supply-chain shifts, or multi-billion-dollar commitments. Routine news is 3–6.
- credibility_score 0–10: lower for speculation, rumours, unnamed sources, or clickbait framing.
- is_funding: true only for a concrete investment, grant/subsidy, M&A, or capex commitment
  with a named recipient.
- summary: 2 factual sentences, no hype.
- metadata: hardware facts if stated (node_nm, hbm_generation, packaging_type, fab_location,
  capacity), else {{}}.

JSON schema:
{{"primary_category": str, "secondary_categories": [str], "subcategories": [str],
  "impact_score": float, "credibility_score": float, "summary": str, "metadata": {{}},
  "is_funding": bool,
  "funding": [{{"company_name": str, "round_type": str|null, "amount_usd": number|null,
               "raw_amount_string": str|null, "investors": [str]}}]}}"""


def analyze(title: str, text: str, source_name: str, hint: str | None) -> dict:
    resp = ai.chat.completions.create(
        model=LLM_MODEL,
        response_format={"type": "json_object"},
        temperature=0.1,
        messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(
            title=title, source=source_name, text=text[:6000] or title,
            categories=sorted(CATEGORIES), subcategories=sorted(SUBCATEGORIES),
        )}],
    )
    data = json.loads(resp.choices[0].message.content)

    # Validate everything — the LLM output goes straight into enum columns.
    cat = data.get("primary_category")
    data["primary_category"] = cat if cat in CATEGORIES else (hint or "ai_infrastructure")
    data["secondary_categories"] = [c for c in data.get("secondary_categories") or []
                                    if c in CATEGORIES and c != data["primary_category"]]
    data["subcategories"] = [s for s in data.get("subcategories") or [] if s in SUBCATEGORIES]
    data["impact_score"] = clamp(data.get("impact_score"), 5.0)
    data["credibility_score"] = clamp(data.get("credibility_score"), 5.0)
    data["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    data["funding"] = [f for f in data.get("funding") or []
                       if isinstance(f, dict) and f.get("company_name")]
    data["is_funding"] = bool(data.get("is_funding")) and bool(data["funding"])
    return data


def clamp(v, default: float) -> float:
    try:
        return round(min(10.0, max(0.0, float(v))), 1)
    except (TypeError, ValueError):
        return default


def embed(text: str) -> list[float]:
    return ai.embeddings.create(model=EMBED_MODEL, input=text[:8000]).data[0].embedding


def is_semantic_duplicate(embedding: list[float]) -> bool:
    res = supabase.rpc("match_similar_articles", {
        "query_embedding": embedding,
        "similarity_threshold": SIMILARITY_THRESHOLD,
    }).execute()
    if res.data:
        log.info("  semantic dup of '%s' (%.3f)", res.data[0]["title"], res.data[0]["similarity"])
        return True
    return False


# ----------------------------------------------------------------------------- main loop
def process_source(source: dict) -> int:
    collect = candidates_from_rss if source["source_type"] == "rss_feed" else candidates_from_scrape
    candidates = collect(source)
    log.info("%s: %d candidates", source["name"], len(candidates))
    if not candidates:
        return 0

    # Batch URL-hash dedup in one query instead of one per link.
    for c in candidates:
        c["url"] = normalize_url(c["url"])
        c["url_hash"] = url_hash(c["url"])
    hashes = list({c["url_hash"] for c in candidates})
    existing = set()
    for i in range(0, len(hashes), 200):
        res = supabase.table("articles").select("url_hash").in_("url_hash", hashes[i:i + 200]).execute()
        existing.update(r["url_hash"] for r in res.data)

    new = [c for c in candidates if c["url_hash"] not in existing][:MAX_NEW_PER_SOURCE]
    inserted = 0
    for c in new:
        try:
            body, page_date = "", None
            html = fetch(c["url"])
            if html:
                body, page_date = extract_body(html)
            text = body or c.get("rss_summary") or ""
            if not c["title"] or len(text) < 120:
                continue  # not a real article page (index page, paywall stub, etc.)

            embedding = embed(f"{c['title']}\n\n{text[:4000]}")
            if is_semantic_duplicate(embedding):
                continue

            a = analyze(c["title"], text, source["name"], source.get("default_category"))
            row = {
                "source_id": source["id"],
                "url": c["url"],
                "url_hash": c["url_hash"],
                "title": c["title"][:1000],
                "summary": a.get("summary"),
                "full_content": text[:50000] or None,
                "author": (c.get("author") or None),
                "published_at": c.get("published_at") or page_date or now_iso(),
                "primary_category": a["primary_category"],
                "secondary_categories": a["secondary_categories"],
                "subcategories": a["subcategories"],
                "impact_score": a["impact_score"],
                "credibility_score": a["credibility_score"],
                "is_funding_related": a["is_funding"],
                "embedding": embedding,
                "metadata": a["metadata"],
            }
            # upsert on url_hash: safe if two runs overlap
            res = supabase.table("articles").upsert(row, on_conflict="url_hash",
                                                    ignore_duplicates=True).execute()
            if not res.data:
                continue
            article_id = res.data[0]["id"]
            inserted += 1
            log.info("  + [%s %.1f] %s", a["primary_category"], a["impact_score"], c["title"][:90])

            if a["is_funding"]:
                supabase.table("funding_events").upsert([{
                    "article_id": article_id,
                    "company_name": f["company_name"][:255],
                    "round_type": f.get("round_type"),
                    "amount_usd": f.get("amount_usd") if isinstance(f.get("amount_usd"), (int, float)) else None,
                    "raw_amount_string": (f.get("raw_amount_string") or "Undisclosed")[:100],
                    "investors": [i for i in f.get("investors") or [] if isinstance(i, str)],
                    "sector": a["primary_category"],
                    "announced_at": row["published_at"],
                } for f in a["funding"]], on_conflict="article_id,company_name",
                    ignore_duplicates=True).execute()
        except Exception:
            log.exception("  failed on %s", c["url"])
        time.sleep(0.5)  # be polite to source sites
    return inserted


def main() -> None:
    sources = supabase.table("rss_sources").select("*").eq("is_active", True).execute().data
    total = 0
    for s in sources:
        last = s.get("last_fetched_at")
        if last:
            age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60
            if age_min < s["fetch_frequency_minutes"] - 5:
                continue
        try:
            total += process_source(s)
        except Exception:
            log.exception("source failed: %s", s["name"])
        finally:
            supabase.table("rss_sources").update({"last_fetched_at": now_iso()}).eq("id", s["id"]).execute()
    log.info("done: %d new articles", total)


if __name__ == "__main__":
    main()
