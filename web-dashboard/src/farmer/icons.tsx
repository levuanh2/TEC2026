import {
  ArrowRight, BookOpen, Calculator, CalendarDays, ChevronRight, Circle, CircleCheck, ClipboardList, Cloud, Clock,
  Droplets, FlaskConical, Fuel, Gauge, History, House, ImagePlus, Info, LandPlot, LayoutDashboard, Leaf, Lightbulb,
  ListChecks, LoaderCircle, LogOut, MapPin, MapPinned, NotebookPen, Pencil, Plus, RefreshCw, Ruler, ScanSearch,
  Scissors, Search, ShieldCheck, Sprout, Sun, Trash2, TriangleAlert, UserRound, WalletCards, Wheat, X,
  type LucideIcon,
} from 'lucide-react'

/* One icon family for all of Farmer Web. Pages ask for a semantic name so the
 * same concept always renders the same glyph (nav, quick actions, journal,
 * forms, detail cards). */
const ICONS = {
  home: House,
  journal: NotebookPen,
  farm: MapPinned,
  plot: LandPlot,
  performance: Gauge,
  account: UserRound,
  seeding: Sprout,
  fertilizer: FlaskConical,
  irrigation: Droplets,
  pesticide: ShieldCheck,
  straw: Wheat,
  harvest: Scissors,
  fuel: Fuel,
  carbon: Cloud,
  leaf: Leaf,
  recommendation: Lightbulb,
  task: ClipboardList,
  info: Info,
  cv: ScanSearch,
  calendar: CalendarDays,
  area: Ruler,
  money: WalletCards,
  chevron: ChevronRight,
  arrow: ArrowRight,
  plus: Plus,
  edit: Pencil,
  delete: Trash2,
  close: X,
  logout: LogOut,
  warning: TriangleAlert,
  check: CircleCheck,
  pending: Circle,
  image: ImagePlus,
  spinner: LoaderCircle,
  overview: LayoutDashboard,
  search: Search,
  refresh: RefreshCw,
  history: History,
  clock: Clock,
  pin: MapPin,
  checklist: ListChecks,
  method: BookOpen,
  calculator: Calculator,
  sun: Sun,
} satisfies Record<string, LucideIcon>

export type IconName = keyof typeof ICONS

export function Ico({ name, className, size }: { name: IconName; className?: string; size?: number }) {
  const Glyph = ICONS[name]
  return <Glyph aria-hidden="true" focusable="false" className={className} size={size} strokeWidth={2} />
}
