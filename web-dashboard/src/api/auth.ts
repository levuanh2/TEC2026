import type { Session } from '@supabase/supabase-js'
import { supabase } from '../utils/supabase'
import { setAccessToken } from './client'
function requireAuthClient() { if (!supabase) throw new Error('Thiếu VITE_SUPABASE_URL hoặc VITE_SUPABASE_PUBLISHABLE_KEY.'); return supabase }
export async function restoreSession(): Promise<Session | null> { const { data, error } = await requireAuthClient().auth.getSession(); if (error) throw error; setAccessToken(data.session?.access_token ?? null); return data.session }
export async function signIn(email: string, password: string) { const { data, error } = await requireAuthClient().auth.signInWithPassword({ email, password }); if (error) throw error; setAccessToken(data.session?.access_token ?? null); return data.session }
export async function signOut() { const { error } = await requireAuthClient().auth.signOut(); setAccessToken(null); if (error) throw error }
