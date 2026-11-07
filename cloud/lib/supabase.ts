import { createClient, SupabaseClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// null when env isn't configured → the dashboard falls back to demo data.
export const supabase: SupabaseClient | null =
  url && anonKey ? createClient(url, anonKey) : null;

export type Category =
  | 'renewable_energy' | 'ai_infrastructure' | 'semiconductors' | 'gpu_production'
  | 'finance' | 'education' | 'automations' | 'automobiles';

export interface Article {
  id: string;
  title: string;
  summary: string | null;
  url: string;
  primary_category: Category;
  subcategories: string[];
  impact_score: number | null;
  is_game_changer: boolean;
  published_at: string; // ISO timestamp
}

export interface FundingEvent {
  id: string;
  company_name: string;
  raw_amount_string: string | null;
  round_type: string | null;
  sector: Category;
  announced_at: string;
}

export type BookmarkType = 'primary' | 'secondary';
