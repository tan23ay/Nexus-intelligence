-- =============================================================================
-- Nexus Intelligence — Supabase / PostgreSQL schema
-- Sectors: Renewable Energy, AI Infra, Semiconductors, GPU Production, + others
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- -----------------------------------------------------------------------------
-- 1. ENUMS
-- -----------------------------------------------------------------------------
CREATE TYPE content_category AS ENUM (
    'renewable_energy',
    'ai_infrastructure',
    'semiconductors',     -- Foundry, silicon, lithography, wafer fabs
    'gpu_production',     -- Accelerators, HBM, CoWoS / advanced packaging
    'finance',
    'education',
    'automations',
    'automobiles'
);

-- Hardware subcategories called out in the architecture (previously only in the
-- diagram; now a real, filterable column instead of free-form JSON).
CREATE TYPE hardware_subcategory AS ENUM (
    'advanced_packaging_cowos',
    'hbm_memory',
    'gpu_accelerators',
    'wafer_fabs',
    'lithography',
    'custom_asics'
);

CREATE TYPE source_type   AS ENUM ('rss_feed', 'web_scraper', 'linkedin_post', 'api_feed');
CREATE TYPE bookmark_type AS ENUM ('primary', 'secondary');

-- -----------------------------------------------------------------------------
-- 2. SOURCES
-- -----------------------------------------------------------------------------
CREATE TABLE public.rss_sources (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                     VARCHAR(255) NOT NULL,
    url                      TEXT NOT NULL UNIQUE,
    source_type              source_type NOT NULL DEFAULT 'rss_feed',
    default_category         content_category,          -- hint for the LLM
    is_active                BOOLEAN NOT NULL DEFAULT TRUE,
    last_fetched_at          TIMESTAMPTZ,
    fetch_frequency_minutes  INT NOT NULL DEFAULT 60,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- NOTE: rss_feed rows must point at an actual feed URL (…/feed/), not a homepage.
INSERT INTO public.rss_sources (name, url, source_type, default_category) VALUES
('IEA Renewables',          'https://www.iea.org/energy-system/renewables-and-low-emissions-fuels', 'web_scraper', 'renewable_energy'),
('Mercom India',            'https://www.mercomindia.com/feed',                                    'rss_feed',    'renewable_energy'),
('ET EnergyWorld',          'https://energy.economictimes.indiatimes.com/news/renewable',          'web_scraper', 'renewable_energy'),
('Renewable Energy Mag',    'https://www.renewableenergymagazine.com/',                            'web_scraper', 'renewable_energy'),
('Recharge News',           'https://www.rechargenews.com/',                                       'web_scraper', 'renewable_energy'),
('Renewables Now',          'https://renewablesnow.com/',                                          'web_scraper', 'renewable_energy'),
('AI Magazine',             'https://aimagazine.com/',                                             'web_scraper', 'ai_infrastructure'),
('Channel Insider',         'https://www.channelinsider.com/feed/',                                'rss_feed',    'ai_infrastructure'),
('TechCrunch AI',           'https://techcrunch.com/category/artificial-intelligence/feed/',       'rss_feed',    'ai_infrastructure'),
('WSJ Tech',                'https://feeds.a.dj.com/rss/RSSWSJD.xml',                              'rss_feed',    'ai_infrastructure'),
('TSMC Newsroom',           'https://pr.tsmc.com/english/latest-news',                             'web_scraper', 'semiconductors'),
('ASML News',               'https://www.asml.com/en/news',                                        'web_scraper', 'semiconductors'),
('SemiMedia',               'https://www.semimedia.cc/feed',                                       'rss_feed',    'semiconductors'),
('India Semiconductor Mission','https://ism.gov.in/',                                              'web_scraper', 'semiconductors'),
('NVIDIA Newsroom',         'https://nvidianews.nvidia.com/',                                      'web_scraper', 'gpu_production'),
('AMD Newsroom',            'https://www.amd.com/en/newsroom.html',                                'web_scraper', 'gpu_production');

-- -----------------------------------------------------------------------------
-- 3. ARTICLES
-- -----------------------------------------------------------------------------
CREATE TABLE public.articles (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id             UUID REFERENCES public.rss_sources(id) ON DELETE SET NULL,
    url                   TEXT NOT NULL UNIQUE,
    url_hash              CHAR(64) NOT NULL UNIQUE,      -- SHA-256 of normalized URL
    title                 TEXT NOT NULL,
    summary               TEXT,
    full_content          TEXT,
    author                VARCHAR(255),
    published_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    scraped_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    primary_category      content_category NOT NULL,
    secondary_categories  content_category[] NOT NULL DEFAULT '{}',
    subcategories         hardware_subcategory[] NOT NULL DEFAULT '{}',

    impact_score          NUMERIC(3,1) CHECK (impact_score BETWEEN 0 AND 10),
    is_game_changer       BOOLEAN GENERATED ALWAYS AS (COALESCE(impact_score >= 8.5, FALSE)) STORED,
    credibility_score     NUMERIC(3,1) NOT NULL DEFAULT 5.0 CHECK (credibility_score BETWEEN 0 AND 10),
    is_funding_related    BOOLEAN NOT NULL DEFAULT FALSE,
    is_verified_fact      BOOLEAN NOT NULL DEFAULT FALSE, -- must be earned, not defaulted

    embedding             vector(1536),                   -- text-embedding-3-small
    metadata              JSONB NOT NULL DEFAULT '{}'::jsonb -- node_nm, hbm_gen, fab_location…
);

-- -----------------------------------------------------------------------------
-- 4. FUNDING EVENTS
-- -----------------------------------------------------------------------------
CREATE TABLE public.funding_events (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id         UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
    company_name       VARCHAR(255) NOT NULL,
    round_type         VARCHAR(100),          -- 'Series A', 'CHIPS Act Grant', 'M&A', 'Fab CapEx'…
    amount_usd         NUMERIC(18,2),         -- 15,2 overflowed above ~$10T; fab capex is large
    raw_amount_string  VARCHAR(100),
    investors          TEXT[] NOT NULL DEFAULT '{}',
    sector             content_category NOT NULL,
    announced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (article_id, company_name)
);

-- -----------------------------------------------------------------------------
-- 5. USER STATE
-- -----------------------------------------------------------------------------
CREATE TABLE public.user_reads (
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    article_id  UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
    read_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, article_id)
);

CREATE TABLE public.user_bookmarks (
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    article_id  UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
    type        bookmark_type NOT NULL DEFAULT 'primary',
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, article_id, type)   -- an article may hold both bookmark types
);

-- -----------------------------------------------------------------------------
-- 6. INDEXES
-- -----------------------------------------------------------------------------
CREATE INDEX idx_articles_feed          ON public.articles (primary_category, published_at DESC);
CREATE INDEX idx_articles_published_at  ON public.articles (published_at DESC);
CREATE INDEX idx_articles_game_changer  ON public.articles (published_at DESC) WHERE is_game_changer;
CREATE INDEX idx_articles_funding       ON public.articles (published_at DESC) WHERE is_funding_related;
CREATE INDEX idx_articles_subcats_gin   ON public.articles USING gin (subcategories);
CREATE INDEX idx_articles_metadata_gin  ON public.articles USING gin (metadata);
CREATE INDEX idx_funding_announced      ON public.funding_events (announced_at DESC);
CREATE INDEX idx_funding_article        ON public.funding_events (article_id);
CREATE INDEX idx_user_bookmarks_article ON public.user_bookmarks (article_id);

-- HNSW instead of IVFFlat: IVFFlat built on an empty table has useless centroids
-- and needs periodic rebuilds; HNSW works from row one.
CREATE INDEX idx_articles_embedding ON public.articles
    USING hnsw (embedding vector_cosine_ops);

-- -----------------------------------------------------------------------------
-- 7. SEMANTIC DEDUP RPC (called by ingest.py via supabase.rpc)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.match_similar_articles(
    query_embedding vector(1536),
    similarity_threshold FLOAT DEFAULT 0.92,
    lookback_days INT DEFAULT 7
)
RETURNS TABLE (id UUID, title TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
    SELECT a.id, a.title, 1 - (a.embedding <=> query_embedding) AS similarity
    FROM public.articles a
    WHERE a.embedding IS NOT NULL
      AND a.published_at > now() - make_interval(days => lookback_days)
      AND 1 - (a.embedding <=> query_embedding) >= similarity_threshold
    ORDER BY a.embedding <=> query_embedding
    LIMIT 1;
$$;

-- Only the service role (ingest worker) may call it.
REVOKE EXECUTE ON FUNCTION public.match_similar_articles FROM PUBLIC, anon, authenticated;

-- -----------------------------------------------------------------------------
-- 8. ROW LEVEL SECURITY
-- (service_role bypasses RLS, so the ingest worker needs no write policies;
--  anon/authenticated get read-only access to content.)
-- -----------------------------------------------------------------------------
ALTER TABLE public.rss_sources    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.articles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.funding_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_reads     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_bookmarks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "read articles"       ON public.articles       FOR SELECT USING (true);
CREATE POLICY "read funding events" ON public.funding_events FOR SELECT USING (true);
CREATE POLICY "read sources"        ON public.rss_sources    FOR SELECT USING (true);

CREATE POLICY "own reads" ON public.user_reads FOR ALL TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own bookmarks" ON public.user_bookmarks FOR ALL TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Lean feed view so browsers never pull 1536-d embeddings or full text.
-- (A column-level REVOKE would be a no-op: Supabase grants table-level SELECT.)
CREATE VIEW public.article_feed WITH (security_invoker = true) AS
SELECT id, url, title, summary, author, published_at, primary_category,
       secondary_categories, subcategories, impact_score, is_game_changer,
       credibility_score, is_funding_related, metadata
FROM public.articles;

-- Realtime for the funding sidebar
ALTER PUBLICATION supabase_realtime ADD TABLE public.funding_events;
