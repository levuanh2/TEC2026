import {
  ArrowRight, Ban, Building2, BookOpen, Calculator, CalendarDays, CalendarRange, ChartNoAxesCombined, Check,
  ChevronRight, Circle, CircleAlert, CircleCheck, ClipboardCheck, ClipboardList, Cloud, Clock, Download, Droplets,
  FileSearch, FlaskConical, Fuel, Gauge, History, House, ImagePlus, Info, LandPlot, LayoutDashboard, Leaf, Lightbulb,
  ListChecks, LoaderCircle, Lock, LogOut, MapPin, MapPinned, Menu, NotebookPen, Paperclip, Pencil, Plus, RefreshCw,
  Ellipsis, Ruler, ScanSearch, Scissors, Search, ShieldCheck, SlidersHorizontal, Sprout, Sun, Tractor, Trash2, TriangleAlert,
  UserRound, WalletCards, Wheat, X,
  type LucideIcon,
} from 'lucide-react'

/* One icon family for the whole product.
 *
 * Farmer and Management are different work modes but the same product, so a
 * concept renders as the same mark in both: a farm is a farm, carbon is carbon.
 * Management used to draw its icons as Unicode glyphs (⬡ ◧ ◈ ✓) and its
 * activity types as emoji (🌱 🧪 💧 🚜) — two vocabularies in one product, and
 * emoji render per-OS, sit outside the type system, and read as a generated-UI
 * tell. Everything is Lucide now.
 *
 * Callers ask for a semantic name, never a glyph, so the mapping stays in one
 * place and a rename never leaks into a page. */
const ICONS = {
  /* --- navigation & places ------------------------------------------- */
  home: House,
  overview: LayoutDashboard,
  organization: Building2,
  farm: MapPinned,
  farms: Tractor,
  plot: LandPlot,
  season: CalendarRange,
  journal: NotebookPen,
  performance: Gauge,
  analytics: ChartNoAxesCombined,
  account: UserRound,
  mrv: ClipboardCheck,

  /* --- field operations (shared with Farmer) -------------------------- */
  seeding: Sprout,
  fertilizer: FlaskConical,
  irrigation: Droplets,
  pesticide: ShieldCheck,
  straw: Wheat,
  harvest: Scissors,
  fuel: Fuel,

  /* --- domain --------------------------------------------------------- */
  carbon: Cloud,
  leaf: Leaf,
  recommendation: Lightbulb,
  task: ClipboardList,
  cv: ScanSearch,
  evidence: Paperclip,
  provenance: FileSearch,
  method: BookOpen,
  calculator: Calculator,

  /* --- measures ------------------------------------------------------- */
  calendar: CalendarDays,
  area: Ruler,
  money: WalletCards,
  clock: Clock,
  history: History,
  pin: MapPin,
  checklist: ListChecks,
  sun: Sun,

  /* --- controls ------------------------------------------------------- */
  chevron: ChevronRight,
  arrow: ArrowRight,
  plus: Plus,
  edit: Pencil,
  delete: Trash2,
  close: X,
  more: Ellipsis,
  logout: LogOut,
  search: Search,
  filter: SlidersHorizontal,
  export: Download,
  refresh: RefreshCw,
  menu: Menu,
  image: ImagePlus,
  spinner: LoaderCircle,

  /* --- state ---------------------------------------------------------- */
  info: Info,
  warning: TriangleAlert,
  error: CircleAlert,
  check: CircleCheck,
  tick: Check,
  pending: Circle,
  denied: Lock,
  blocked: Ban,
} satisfies Record<string, LucideIcon>

export type IconName = keyof typeof ICONS

export function Ico({ name, className, size }: { name: IconName; className?: string; size?: number }) {
  const Glyph = ICONS[name]
  return <Glyph aria-hidden="true" focusable="false" className={className} size={size} strokeWidth={2} />
}
