'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckSquare, Square, Bookmark, Star, Zap, Cpu, CircuitBoard, Flame,
  DollarSign, Car, GraduationCap, Bot, Layers, Eye, EyeOff, Sun,
} from 'lucide-react';
import {
  supabase, type Article, type BookmarkType, type Category, type FundingEvent,
} from '@/lib/supabase';

// ----------------------------------------------------------------------------- config
const CATEGORIES = [
  { id: 'all', label: 'All Intelligence', icon: Layers },
  { id: 'saved', label: 'Saved', icon: Bookmark },
  { id: 'renewable_energy', label: 'Renewable Energy', icon: Sun },
  { id: 'ai_infrastructure', label: 'AI Infrastructure', icon: Zap },
  { id: 'semiconductors', label: 'Semiconductors', icon: CircuitBoard },
  { id: 'gpu_production', label: 'GPUs & Packaging', icon: Cpu },
  { id: 'finance', label: 'Finance', icon: DollarSign },
  { id: 'education', label: 'Education', icon: GraduationCap },
  { id: 'automations', label: 'Automations', icon: Bot },
  { id: 'automobiles', label: 'Automobiles', icon: Car },
] as const;
type TabId = (typeof CATEGORIES)[number]['id'];

const ARTICLE_COLUMNS =
  'id,title,summary,url,primary_category,subcategories,impact_score,is_game_changer,published_at';

const LOCAL_KEY = 'nexus-user-state-v1';

const label = (s: string) => s.replaceAll('_', ' ');

function timeAgo(iso: string) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

// ----------------------------------------------------------------------------- demo data
const ago = (m: number) => new Date(Date.now() - m * 60000).toISOString();
const DEMO_ARTICLES: Article[] = [
  { id: 'd1', title: 'Foundry begins 2nm GAA trial production alongside new CoWoS line for HBM4 modules',
    summary: 'Demo item. Trial 2nm output and added advanced-packaging capacity aimed at next-gen accelerators.',
    url: '#', primary_category: 'gpu_production', subcategories: ['wafer_fabs', 'advanced_packaging_cowos', 'hbm_memory'],
    impact_score: 9.1, is_game_changer: true, published_at: ago(10) },
  { id: 'd2', title: 'Tandem perovskite-silicon modules pass extended outdoor reliability testing',
    summary: 'Demo item. Pilot modules clear damp-heat and thermal-cycling tests ahead of commercial scale-up.',
    url: '#', primary_category: 'renewable_energy', subcategories: [],
    impact_score: 8.6, is_game_changer: true, published_at: ago(45) },
  { id: 'd3', title: 'AI optical inspection cuts micro-bump defects in 3D packaging lines',
    summary: 'Demo item. Automated inspection reduces rework in advanced-packaging back-end flows.',
    url: '#', primary_category: 'automations', subcategories: ['advanced_packaging_cowos'],
    impact_score: 6.8, is_game_changer: false, published_at: ago(70) },
];
const DEMO_FUNDING: FundingEvent[] = [
  { id: 'f1', company_name: 'Example Fab Co', raw_amount_string: '$6.5B', round_type: 'Fab Subsidy',
    sector: 'semiconductors', announced_at: ago(30) },
  { id: 'f2', company_name: 'Example Thermal Labs', raw_amount_string: '$120M', round_type: 'Series B',
    sector: 'ai_infrastructure', announced_at: ago(200) },
];

// ----------------------------------------------------------------------------- user state
// Reads + bookmarks persist to Supabase when signed in, otherwise to localStorage.
type Bookmarks = Record<string, Partial<Record<BookmarkType, true>>>;

function useUserState() {
  const [userId, setUserId] = useState<string | null>(null);
  const [reads, setReads] = useState<Set<string>>(new Set());
  const [bookmarks, setBookmarks] = useState<Bookmarks>({});

  useEffect(() => {
    (async () => {
      const { data } = supabase ? await supabase.auth.getUser() : { data: { user: null } };
      const uid = data.user?.id ?? null;
      setUserId(uid);
      if (supabase && uid) {
        const [r, b] = await Promise.all([
          supabase.from('user_reads').select('article_id'),
          supabase.from('user_bookmarks').select('article_id,type'),
        ]);
        setReads(new Set((r.data ?? []).map((x) => x.article_id)));
        const bm: Bookmarks = {};
        for (const x of b.data ?? []) (bm[x.article_id] ??= {})[x.type as BookmarkType] = true;
        setBookmarks(bm);
      } else {
        try {
          const saved = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '{}');
          setReads(new Set(saved.reads ?? []));
          setBookmarks(saved.bookmarks ?? {});
        } catch { /* storage unavailable */ }
      }
    })();
  }, []);

  useEffect(() => {
    if (userId) return;
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify({ reads: [...reads], bookmarks }));
    } catch { /* storage unavailable */ }
  }, [reads, bookmarks, userId]);

  const toggleRead = useCallback((id: string) => {
    const wasRead = reads.has(id);
    setReads((prev) => {
      const next = new Set(prev);
      wasRead ? next.delete(id) : next.add(id);
      return next;
    });
    if (supabase && userId) {
      const t = supabase.from('user_reads');
      void (wasRead
        ? t.delete().match({ user_id: userId, article_id: id })
        : t.upsert({ user_id: userId, article_id: id }));
    }
  }, [reads, userId]);

  // Primary and secondary are independent — an article can carry both.
  const toggleBookmark = useCallback((id: string, type: BookmarkType) => {
    const had = !!bookmarks[id]?.[type];
    setBookmarks((prev) => {
      const entry = { ...prev[id] };
      had ? delete entry[type] : (entry[type] = true);
      const next = { ...prev, [id]: entry };
      if (!Object.keys(entry).length) delete next[id];
      return next;
    });
    if (supabase && userId) {
      const t = supabase.from('user_bookmarks');
      void (had
        ? t.delete().match({ user_id: userId, article_id: id, type })
        : t.upsert({ user_id: userId, article_id: id, type }));
    }
  }, [bookmarks, userId]);

  return { reads, bookmarks, toggleRead, toggleBookmark, signedIn: !!userId };
}

// ----------------------------------------------------------------------------- page
export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('all');
  const [sort, setSort] = useState<'impact' | 'date'>('date');
  const [showRead, setShowRead] = useState(false);
  const [articles, setArticles] = useState<Article[]>([]);
  const [funding, setFunding] = useState<FundingEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { reads, bookmarks, toggleRead, toggleBookmark, signedIn } = useUserState();

  useEffect(() => {
    if (!supabase) {
      setArticles(DEMO_ARTICLES);
      setFunding(DEMO_FUNDING);
      setLoading(false);
      return;
    }
    const sb = supabase;
    const since = new Date(Date.now() - 7 * 86400000).toISOString();
    (async () => {
      const [a, f] = await Promise.all([
        sb.from('article_feed').select(ARTICLE_COLUMNS)
          .gte('published_at', since).order('published_at', { ascending: false }).limit(300),
        sb.from('funding_events')
          .select('id,company_name,raw_amount_string,round_type,sector,announced_at')
          .order('announced_at', { ascending: false }).limit(30),
      ]);
      if (a.error || f.error) setError((a.error ?? f.error)!.message);
      setArticles((a.data as Article[]) ?? []);
      setFunding((f.data as FundingEvent[]) ?? []);
      setLoading(false);
    })();

    // Live funding sidebar
    const channel = sb.channel('funding')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'funding_events' },
        (p) => setFunding((prev) => [p.new as FundingEvent, ...prev].slice(0, 30)))
      .subscribe();
    return () => { void sb.removeChannel(channel); };
  }, []);

  const visible = useMemo(() => {
    const list = articles.filter((a) => {
      if (activeTab === 'saved') return !!bookmarks[a.id];
      if (!showRead && reads.has(a.id)) return false;
      return activeTab === 'all' || a.primary_category === activeTab;
    });
    return list.sort((x, y) =>
      sort === 'impact'
        ? (y.impact_score ?? 0) - (x.impact_score ?? 0)
        : +new Date(y.published_at) - +new Date(x.published_at));
  }, [articles, activeTab, showRead, reads, bookmarks, sort]);

  const heroes = activeTab === 'saved' ? [] : visible.filter((a) => a.is_game_changer).slice(0, 2);
  const feed = visible.filter((a) => !heroes.includes(a));

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur px-4 sm:px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-lg"><Zap className="h-6 w-6 text-white" /></div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white">NEXUS INTELLIGENCE</h1>
            <p className="text-xs text-slate-400">Hourly energy, AI infrastructure & semiconductor radar</p>
          </div>
        </div>
        <span className="text-[11px] text-slate-500">
          {!supabase ? 'Demo data' : signedIn ? 'Synced to your account' : 'Saved on this device'}
        </span>
      </header>

      <div className="flex flex-1">
        <main className="flex-1 min-w-0 p-4 sm:p-6 max-w-5xl">
          <nav className="flex items-center gap-2 overflow-x-auto pb-4 mb-4 border-b border-slate-800">
            {CATEGORIES.map(({ id, label: text, icon: Icon }) => (
              <button key={id} onClick={() => setActiveTab(id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold whitespace-nowrap transition-all ${
                  activeTab === id ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20'
                    : 'bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}>
                <Icon className="h-3.5 w-3.5" />{text}
              </button>
            ))}
          </nav>

          <div className="flex items-center justify-between mb-4 text-xs text-slate-400">
            <div className="flex gap-1 bg-slate-900 rounded-lg p-1">
              {(['date', 'impact'] as const).map((s) => (
                <button key={s} onClick={() => setSort(s)}
                  className={`px-3 py-1 rounded-md ${sort === s ? 'bg-slate-700 text-white' : 'hover:text-slate-200'}`}>
                  {s === 'date' ? 'Latest' : 'Highest impact'}
                </button>
              ))}
            </div>
            {activeTab !== 'saved' && (
              <button onClick={() => setShowRead((v) => !v)} className="flex items-center gap-1.5 hover:text-slate-200">
                {showRead ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {showRead ? 'Hide read' : `Show read (${reads.size})`}
              </button>
            )}
          </div>

          {error && <p className="mb-4 text-sm text-red-400">Couldn’t load feed: {error}</p>}

          {heroes.length > 0 && (
            <section className="grid gap-4 md:grid-cols-2 mb-6">
              {heroes.map((a) => (
                <ArticleCard key={a.id} article={a} hero read={reads.has(a.id)} marks={bookmarks[a.id]}
                  onRead={toggleRead} onBookmark={toggleBookmark} />
              ))}
            </section>
          )}

          <div className="space-y-4">
            {feed.map((a) => (
              <ArticleCard key={a.id} article={a} read={reads.has(a.id)} marks={bookmarks[a.id]}
                onRead={toggleRead} onBookmark={toggleBookmark} />
            ))}
            {!loading && visible.length === 0 && (
              <div className="text-center py-12 text-slate-500 border border-dashed border-slate-800 rounded-xl">
                {activeTab === 'saved' ? 'Nothing bookmarked yet.' : 'No unread news here. Check back next hour.'}
              </div>
            )}
            {loading && <div className="text-center py-12 text-slate-500">Loading…</div>}
          </div>
        </main>

        <aside className="w-80 shrink-0 border-l border-slate-800 bg-slate-900/20 p-5 hidden lg:block">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="h-5 w-5 text-emerald-400" />
            <h2 className="font-bold text-sm tracking-wide text-slate-200">DEAL FLOW & FUNDING</h2>
          </div>
          <div className="space-y-3">
            {funding.map((f) => (
              <div key={f.id} className="p-3 bg-slate-900 border border-slate-800 rounded-lg space-y-1">
                <div className="flex justify-between items-center gap-2">
                  <span className="font-semibold text-sm text-slate-200 truncate">{f.company_name}</span>
                  <span className="text-xs font-mono font-bold text-emerald-400 shrink-0">{f.raw_amount_string ?? 'Undisclosed'}</span>
                </div>
                <div className="flex justify-between items-center text-[11px] text-slate-400">
                  <span>{f.round_type ?? 'Investment'} · {timeAgo(f.announced_at)}</span>
                  <span className="uppercase text-[9px] bg-slate-800 px-1.5 py-0.5 rounded">{label(f.sector)}</span>
                </div>
              </div>
            ))}
            {funding.length === 0 && !loading && <p className="text-xs text-slate-500">No deals yet.</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- card
function ArticleCard({ article: a, hero, read, marks, onRead, onBookmark }: {
  article: Article; hero?: boolean; read: boolean;
  marks?: Partial<Record<BookmarkType, true>>;
  onRead: (id: string) => void; onBookmark: (id: string, t: BookmarkType) => void;
}) {
  return (
    <article className={`p-5 rounded-xl border transition-all ${read ? 'opacity-50' : ''} ${
      a.is_game_changer ? 'bg-slate-900/90 border-amber-500/40 shadow-lg shadow-amber-500/5'
        : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'}`}>
      <div className="flex justify-between items-start gap-4">
        <div className="space-y-2 flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {a.is_game_changer && (
              <span className="bg-amber-500/10 text-amber-400 border border-amber-500/30 text-[10px] font-extrabold px-2 py-0.5 rounded-md flex items-center gap-1">
                <Flame className="h-3 w-3" /> GAME-CHANGER {a.impact_score?.toFixed(1)}/10
              </span>
            )}
            <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
              {label(a.primary_category as Category)}
            </span>
            {a.subcategories?.map((s) => (
              <span key={s} className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-300">{label(s)}</span>
            ))}
            <span className="text-xs text-slate-500">{timeAgo(a.published_at)}</span>
          </div>
          <a href={a.url} target="_blank" rel="noopener noreferrer"
            className={`${hero ? 'text-xl' : 'text-lg'} font-semibold text-slate-100 hover:text-blue-400 block`}>
            {a.title}
          </a>
          {a.summary && <p className="text-sm text-slate-400 leading-relaxed">{a.summary}</p>}
        </div>

        <div className="flex flex-col items-center gap-2 border-l border-slate-800 pl-4">
          <IconBtn title={read ? 'Mark unread' : 'Mark read (dismiss)'} onClick={() => onRead(a.id)}
            active={read} activeCls="text-emerald-400">
            {read ? <CheckSquare className="h-5 w-5" /> : <Square className="h-5 w-5" />}
          </IconBtn>
          <IconBtn title="Primary bookmark" onClick={() => onBookmark(a.id, 'primary')}
            active={!!marks?.primary} activeCls="text-blue-400 bg-blue-500/10">
            <Bookmark className="h-5 w-5" fill={marks?.primary ? 'currentColor' : 'none'} />
          </IconBtn>
          <IconBtn title="Secondary bookmark" onClick={() => onBookmark(a.id, 'secondary')}
            active={!!marks?.secondary} activeCls="text-amber-400 bg-amber-500/10">
            <Star className="h-5 w-5" fill={marks?.secondary ? 'currentColor' : 'none'} />
          </IconBtn>
        </div>
      </div>
    </article>
  );
}

function IconBtn({ title, onClick, active, activeCls, children }: {
  title: string; onClick: () => void; active: boolean; activeCls: string; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} title={title} aria-label={title} aria-pressed={active}
      className={`p-1.5 rounded-lg transition-colors ${active ? activeCls : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'}`}>
      {children}
    </button>
  );
}
