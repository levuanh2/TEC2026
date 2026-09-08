import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// Auth only. Dashboard data is intentionally fetched through FastAPI.
export const supabase = url && publishableKey ? createClient(url, publishableKey) : null
