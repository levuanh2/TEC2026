import type { Session } from '@supabase/supabase-js'
import { supabase } from '../utils/supabase'
import { setAccessToken } from './client'
import { clearOrganizationCache } from './organizations'
import { clearViewerHint } from './me'
import { clearFarmerCache } from '../farmer/data'
function requireAuthClient() { if (!supabase) throw new Error('Thiếu VITE_SUPABASE_URL hoặc VITE_SUPABASE_PUBLISHABLE_KEY.'); return supabase }
export async function restoreSession(): Promise<Session | null> { const { data, error } = await requireAuthClient().auth.getSession(); if (error) throw error; setAccessToken(data.session?.access_token ?? null); return data.session }
export async function signIn(email: string, password: string) { const { data, error } = await requireAuthClient().auth.signInWithPassword({ email, password }); if (error) throw error; setAccessToken(data.session?.access_token ?? null); return data.session }
// Clear the session-scoped org-identity cache on sign-out (brief Part B §20
// caching note) — this SPA navigates to /login via the client-side router,
// not a full page reload, so a stale cache entry could otherwise survive
// into a different signed-in user's session within the same browser tab.
export async function signOut() { const { error } = await requireAuthClient().auth.signOut(); setAccessToken(null); clearOrganizationCache(); clearFarmerCache(); clearViewerHint(); if (error) throw error }
