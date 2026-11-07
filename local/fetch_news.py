"""
Keyless news fetcher for the local Nexus Intelligence site.

Pulls real RSS/Atom feeds (standard library only — no pip installs, no API keys),
classifies each story into a sector with keyword rules, assigns a heuristic
impact score, extracts funding deals with regexes, dedups, and writes
site/data.json for the dashboard.

    python local/fetch_news.py
"""

from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "site" / "data.json"
KEEP_DAYS = 31  # enough history for the "past month" related-news view
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NexusIntelligence/1.0 (personal news reader)"

# (name, feed url, default category)
SOURCES = [
    # Renewable energy
    ("Mercom India", "https://www.mercomindia.com/feed", "renewable_energy"),
    ("pv magazine", "https://www.pv-magazine.com/feed/", "renewable_energy"),
    ("CleanTechnica", "https://cleantechnica.com/feed/", "renewable_energy"),
    ("Renewable Energy World", "https://www.renewableenergyworld.com/feed/", "renewable_energy"),
    ("Electrek", "https://electrek.co/feed/", "renewable_energy"),
    # AI infrastructure
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ai_infrastructure"),
    ("Data Center Dynamics", "https://www.datacenterdynamics.com/en/rss/", "ai_infrastructure"),
    ("ServeTheHome", "https://www.servethehome.com/feed/", "ai_infrastructure"),
    ("Channel Insider", "https://www.channelinsider.com/feed/", "ai_infrastructure"),
    ("The Register", "https://www.theregister.com/headlines.atom", "ai_infrastructure"),
    # Semiconductors & GPUs
    ("Semiconductor Engineering", "https://semiengineering.com/feed/", "semiconductors"),
    ("EE Times", "https://www.eetimes.com/feed/", "semiconductors"),
    ("SemiMedia", "https://www.semimedia.cc/feed", "semiconductors"),
    ("Tom's Hardware", "https://www.tomshardware.com/feeds/all", "gpu_production"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "gpu_production"),
    # Finance / funding
    ("TechCrunch Venture", "https://techcrunch.com/category/venture/feed/", "finance"),
    # Education, automation, autos
    ("EdSurge", "https://www.edsurge.com/articles_rss", "education"),
    ("The Robot Report", "https://www.therobotreport.com/feed/", "automations"),
    ("electrive", "https://www.electrive.com/feed/", "automobiles"),
]

# Keyword rules. More specific hardware sectors are weighted higher so a
# "TSMC CoWoS for NVIDIA GPUs" story lands in gpu_production, not ai_infrastructure.
RULES: dict[str, tuple[float, list[str]]] = {
    "gpu_production": (1.4, [
        "gpu", "gpus", "accelerator", "hbm", "hbm3", "hbm3e", "hbm4", "cowos", "advanced packaging",
        "chiplet", "blackwell", "rubin", "hopper", "h100", "h200", "b200", "gb200", "mi300", "mi325",
        "mi350", "mi400", "instinct", "tpu", "asic", "interposer", "sk hynix", "micron", "geforce",
        "radeon", "nvlink",
    ]),
    "semiconductors": (1.3, [
        "semiconductor", "chip", "chips", "chipmaker", "foundry", "fab", "fabs", "wafer", "tsmc",
        "samsung foundry", "intel foundry", "globalfoundries", "asml", "euv", "lithography", "2nm",
        "3nm", "18a", "14a", "node", "gaa", "gate-all-around", "silicon", "eda", "synopsys",
        "cadence", "chips act", "india semiconductor mission", "osat", "rapidus", "smic", "risc-v",
    ]),
    "ai_infrastructure": (1.0, [
        "data center", "datacenter", "data centre", "hyperscaler", "ai infrastructure", "compute",
        "cluster", "supercomputer", "inference", "training", "llm", "openai", "anthropic", "gemini",
        "cloud", "aws", "azure", "colocation", "liquid cooling", "megawatt", "gigawatt campus",
        "ai model", "artificial intelligence", "generative ai",
    ]),
    "renewable_energy": (1.0, [
        "solar", "photovoltaic", "pv ", "wind", "offshore wind", "renewable", "battery storage",
        "energy storage", "bess", "green hydrogen", "electrolyzer", "perovskite", "geothermal",
        "hydropower", "grid", "transmission", "net zero", "decarboni", "clean energy", "module",
        "inverter", "mw ", "gw ",
    ]),
    "automobiles": (1.0, [
        " ev ", "evs", "electric vehicle", "tesla", "byd", "automaker", "car ", "cars", "charging",
        "charger", "vehicle", "autonomous driving", "robotaxi", "rivian", "volkswagen", "hyundai",
    ]),
    "automations": (1.0, [
        "robot", "robotics", "humanoid", "automation", "automated", "agentic", "ai agent",
        "warehouse", "cobot", "industrial automation", "workflow",
    ]),
    "education": (1.0, [
        "education", "edtech", "school", "students", "teachers", "university", "learning",
        "classroom", "curriculum", "k-12",
    ]),
    "finance": (0.9, [
        "funding", "raises", "series a", "series b", "series c", "seed round", "venture", "vc ",
        "ipo", "valuation", "investors", "acquisition", "acquires", "merger", "fintech", "bank",
        "stock", "earnings", "revenue",
    ]),
}

SUBCATS = {
    "advanced_packaging_cowos": ["cowos", "advanced packaging", "chiplet", "interposer", "3d packaging", "soic", "foveros"],
    "hbm_memory": ["hbm", "high bandwidth memory"],
    "gpu_accelerators": ["gpu", "accelerator", "blackwell", "rubin", "instinct", "tpu", "h100", "h200", "b200", "gb200", "mi3"],
    "wafer_fabs": ["fab", "wafer", "foundry", "2nm", "3nm", "18a", "gate-all-around"],
    "lithography": ["euv", "lithography", "asml", "high-na"],
    "custom_asics": ["asic", "custom silicon", "custom chip", "tpu", "trainium", "inferentia", "mtia"],
}

BIG_SIGNALS = [
    ("breakthrough", 1.5), ("world record", 1.5), ("record", 0.8), ("first-ever", 1.0),
    ("world's first", 1.4), ("unveils", 0.6), ("launches", 0.5), ("inaugurat", 1.2),
    ("mass production", 1.3), ("begins production", 1.2), ("groundbreaking", 0.8),
    ("gigafactory", 1.0), ("new fab", 1.3), ("efficiency", 0.4), ("acquire", 0.8),
    ("merger", 0.8), ("ipo", 0.8), ("to buy", 0.8), ("block", 0.6), ("expansion", 0.5),
    ("new plant", 1.0), ("factory", 0.5), ("commissioned", 1.0), ("approves", 0.6), ("export control", 1.0), ("tariff", 0.6), ("ban", 0.5),
    ("shortage", 0.8), ("gigawatt", 0.8), ("2nm", 0.8), ("hbm4", 0.9),
]
NOISE_SIGNALS = ["review", "deal:", "deals", "best ", "how to", "podcast", "webinar", "sponsored",
                 "opinion", "% off", "sale", "giveaway", "hands-on", "rumor", "rumour", "leak"]

MONEY_RE = re.compile(
    r"(?:US)?\$\s?(\d+(?:[.,]\d+)?)\s?(trillion|billion|million|bn|tn|mn|b|m)\b"
    r"|(?:₹|Rs\.?|INR)\s?(\d+(?:[.,]\d+)?)\s?(crore|lakh crore|billion|million)",
    re.I,
)
DEAL_RE = re.compile(
    r"\b(raises?|raised|secures?|secured|closes?|lands?|nabs?|bags?|funding|series [a-f]|seed|"
    r"acquires?|acquired|acquisition|to buy|invest(?:s|ment|ing)?|grant|subsid(?:y|ies)|"
    r"incentive|capex|commit(?:s|ment)?|valuation|ipo)\b",
    re.I,
)
COMPANY_RE = re.compile(
    r"^([A-Z][\w&.'\-]*(?:\s+(?:[A-Z][\w&.'\-]*|AI|Inc\.?|Labs|Energy|Power|Systems))*?)\s+"
    r"(?:(?:reportedly|officially|now|quietly)\s+)?(?:raises|secures|closes|lands|nabs|bags|acquires|to acquire|to buy|buys|gets|wins|announces|"
    r"invests|commits|plans|files)\b"
)
ROUND_RE = re.compile(r"\b(pre-seed|seed|series [a-f]\+?|ipo|acquisition|acquires|merger|grant|"
                      r"subsidy|debt|loan|capex|investment)\b", re.I)


# ----------------------------------------------------------------------------- helpers
def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(The post .* appeared first on .*\.?$)", "", s).strip()
    return s


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))])
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", q, ""))


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


# ----------------------------------------------------------------------------- fetch
def fetch_feed(source: tuple[str, str, str]) -> tuple[str, list[dict], str | None]:
    name, url, default_cat = source
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}), timeout=20) as r:
            raw = r.read()
        root = ET.fromstring(raw)
    except Exception as e:  # network error, 403, malformed XML…
        return name, [], f"{type(e).__name__}: {e}"

    items = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/",
          "content": "http://purl.org/rss/1.0/modules/content/"}
    entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
    for e in entries:
        if e.tag.endswith("entry"):  # Atom
            link_el = e.find("atom:link[@rel='alternate']", ns) or e.find("atom:link", ns)
            link = link_el.get("href") if link_el is not None else None
            title = e.findtext("atom:title", "", ns)
            summary = e.findtext("atom:summary", "", ns) or e.findtext("atom:content", "", ns)
            date = e.findtext("atom:published", None, ns) or e.findtext("atom:updated", None, ns)
            author = e.findtext("atom:author/atom:name", None, ns)
        else:  # RSS 2.0
            link = (e.findtext("link") or "").strip()
            title = e.findtext("title", "")
            summary = e.findtext("description", "") or e.findtext("content:encoded", "", ns)
            date = e.findtext("pubDate") or e.findtext("dc:date", None, ns)
            author = e.findtext("dc:creator", None, ns) or e.findtext("author")
        title = clean_text(title)
        if not link or not title:
            continue
        items.append({
            "title": title,
            "url": normalize_url(link),
            "summary": clean_text(summary)[:600],
            "published": parse_date(date),
            "author": clean_text(author) or None,
            "source": name,
            "default_category": default_cat,
        })
    return name, items, None


# ----------------------------------------------------------------------------- enrich
def classify(title: str, summary: str, default: str) -> tuple[str, list[str], dict[str, float]]:
    t = f" {title.lower()} "
    s = f" {summary.lower()} "
    scores: dict[str, float] = {}
    for cat, (weight, kws) in RULES.items():
        sc = 0.0
        for kw in kws:
            pat = r"(?<![a-z0-9])" + re.escape(kw.strip()) + r"(?![a-z0-9])"
            if re.search(pat, t):
                sc += 3.0
            elif re.search(pat, s):
                sc += 1.0
        if sc:
            scores[cat] = sc * weight
    scores[default] = scores.get(default, 0) + 1.5  # source prior
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    primary = ranked[0][0]
    secondary = [c for c, v in ranked[1:4] if v >= 3.0]
    return primary, secondary, scores


def subcategories(text: str) -> list[str]:
    t = text.lower()
    return [k for k, kws in SUBCATS.items()
            if any(re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t) for kw in kws)]


def money_usd(text: str) -> tuple[float | None, str | None]:
    best: tuple[float | None, str | None] = (None, None)
    for m in MONEY_RE.finditer(text):
        if m.group(1):
            n = float(m.group(1).replace(",", ""))
            unit = m.group(2).lower()
            mult = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
                    "million": 1e6, "mn": 1e6, "m": 1e6}[unit]
            usd = n * mult
        else:
            n = float(m.group(3).replace(",", ""))
            unit = m.group(4).lower()
            inr = n * {"crore": 1e7, "lakh crore": 1e12, "billion": 1e9, "million": 1e6}[unit]
            usd = inr / 85.0  # approx INR→USD
        if best[0] is None or usd > best[0]:
            best = (usd, m.group(0).strip())
    return best


def impact(title: str, summary: str, primary: str, cat_scores: dict[str, float], usd: float | None) -> float:
    t = title.lower()
    full = f"{t} {summary.lower()}"
    score = 4.0
    score += sum(w for kw, w in BIG_SIGNALS if kw in t)
    score += 0.4 * sum(w for kw, w in BIG_SIGNALS if kw in summary.lower() and kw not in t)
    if usd:
        score += (4.0 if usd >= 2e10 else 3.0 if usd >= 5e9 else 2.2 if usd >= 1e9
                  else 1.2 if usd >= 1e8 else 0.4)
    if primary in ("semiconductors", "gpu_production"):
        score += 0.4
    score += min(1.0, cat_scores.get(primary, 0) / 12)  # topical density
    if any(n in full for n in NOISE_SIGNALS):
        score -= 2.0
    return round(max(1.0, min(9.8, score)), 1)


def funding(title: str, summary: str, usd: float | None, raw: str | None, sector: str) -> dict | None:
    if not DEAL_RE.search(title) or (usd is None and not re.search(r"acqui|merger|ipo", title, re.I)):
        return None
    m = COMPANY_RE.search(title)
    company = m.group(1) if m else None
    if not company:
        return None
    # Deal size = first amount in the headline that isn't a valuation/market cap.
    for m in MONEY_RE.finditer(title):
        before, after = title[max(0, m.start() - 6):m.start()].lower(), title[m.end():m.end() + 14].lower()
        if "at a" in before or "valuation" in after or "market cap" in after:
            continue
        usd, raw = money_usd(m.group(0))
        break
    rnd = ROUND_RE.search(f"{title} {summary}")
    round_type = rnd.group(1).title() if rnd else "Investment"
    if re.search(r"\b(to buy|buys|to acquire|acquires|acquisition)\b", title, re.I):
        round_type = "Acquisition"
    round_type = {"Acquires": "Acquisition", "Ipo": "IPO", "Capex": "CapEx"}.get(round_type, round_type)
    return {"company_name": company[:80], "round_type": round_type, "amount_usd": usd,
            "raw_amount_string": raw or "Undisclosed", "sector": sector}


def enrich(item: dict) -> dict:
    primary, secondary, cat_scores = classify(item["title"], item["summary"], item["default_category"])
    text = f"{item['title']} {item['summary']}"
    usd, raw = money_usd(text)
    sc = impact(item["title"], item["summary"], primary, cat_scores, usd)
    f = funding(item["title"], item["summary"], usd, raw, primary)
    subs = subcategories(text) if primary in ("semiconductors", "gpu_production", "ai_infrastructure") else []
    pub = item["published"] or datetime.now(timezone.utc)
    return {
        "id": sha256(item["url"].encode()).hexdigest()[:16],
        "title": item["title"],
        "summary": item["summary"],
        "url": item["url"],
        "source": item["source"],
        "author": item["author"],
        "primary_category": primary,
        "secondary_categories": secondary,
        "subcategories": subs,
        "impact_score": sc,
        "is_game_changer": sc >= 8.5,
        "is_funding_related": f is not None,
        "funding": f,
        "published_at": pub.astimezone(timezone.utc).isoformat(),
    }


# ----------------------------------------------------------------------------- main
def load_existing() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8")).get("articles", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def run() -> dict:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_feed, SOURCES))

    status = []
    fresh: list[dict] = []
    for name, items, err in results:
        status.append({"source": name, "ok": err is None, "count": len(items), "error": err})
        fresh.extend(items)

    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    existing = {a["url"]: a for a in load_existing()
                if datetime.fromisoformat(a["published_at"]) >= cutoff}
    merged = dict(existing)
    seen_titles = [words(a["title"]) for a in merged.values()]

    added = 0
    for it in sorted(fresh, key=lambda x: x["published"] or datetime.now(timezone.utc)):
        if it["url"] in merged:
            continue
        if it["published"] and it["published"] < cutoff:
            continue
        w = words(it["title"])
        # near-duplicate headline from another outlet → skip
        if w and any(len(w & o) / max(1, len(w | o)) >= 0.7 for o in seen_titles):
            continue
        merged[it["url"]] = enrich(it)
        seen_titles.append(w)
        added += 1

    articles = sorted(merged.values(), key=lambda a: a["published_at"], reverse=True)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
        "sources": status,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)

    ok = sum(s["ok"] for s in status)
    print(f"[{datetime.now():%H:%M}] {ok}/{len(status)} feeds ok, {added} new, {len(articles)} total")
    for s in status:
        if not s["ok"]:
            print(f"   ! {s['source']}: {s['error']}", file=sys.stderr)
    return out


if __name__ == "__main__":
    run()
