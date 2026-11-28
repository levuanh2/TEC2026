import { Check, Crown, Droplets, Leaf, Milk, ShieldCheck, Sprout, Star, Wheat } from 'lucide-react'
import { Link } from '../ui'
import { COOPERATIVE_PLANS, FARMER_PLANS, JOURNAL_ACTIVITIES, planSelectionPath, type ServicePlan } from './pricing'

const PLAN_ICONS = { FREE: Sprout, PLUS: Star, PRO: Crown }
const ACTIVITY_ICONS = [Sprout, Milk, Droplets, Leaf, ShieldCheck, Wheat]

export function PricingTables() {
  return <>
    <nav className="pub-pricing-jump" aria-label="Chọn bảng giá"><a href="#nong-ho">Cho nông hộ</a><a href="#hop-tac-xa">Cho hợp tác xã</a></nav>
    <PricingTable id="nong-ho" title="Gói dành cho Nông hộ" description="Dành cho nông hộ sử dụng cá nhân — ghi nhật ký canh tác, tự tính carbon mùa vụ và nhận hỗ trợ từ trợ lý AI." plans={FARMER_PLANS} />
    <section className="pub-journal-strip" aria-label="6 hoạt động nhật ký canh tác"><h3>Nhật ký canh tác ghi lại 6 hoạt động</h3><ul>{JOURNAL_ACTIVITIES.map((label, index) => { const Icon = ACTIVITY_ICONS[index]; return <li key={label}><span><Icon size={23} strokeWidth={1.6} aria-hidden="true" /></span>{label}</li> })}</ul></section>
    <PricingTable id="hop-tac-xa" title="Gói dành cho Hợp tác xã" description="HTX quản lý tập trung và cấp mã tài khoản cho nông dân sử dụng — số hóa canh tác, đo phát thải carbon, sẵn sàng dữ liệu MRV." plans={COOPERATIVE_PLANS} />
  </>
}

function PricingTable({ id, title, description, plans }: { id: string; title: string; description: string; plans: ServicePlan[] }) {
  return <section className="pub-pricing-table" id={id} aria-labelledby={`${id}-title`}>
    <div className="pub-pricing-heading"><p className="pub-eyebrow">BẢNG GIÁ DỊCH VỤ AGRICARBON</p><h2 id={`${id}-title`}>{title}</h2><p>{description}</p></div>
    <div className="pub-pricing-grid">{plans.map((plan) => <PlanCard key={plan.name} plan={plan} audience={id} />)}</div>
  </section>
}

function PlanCard({ plan, audience }: { plan: ServicePlan; audience: string }) {
  const featured = plan.name === 'PLUS'
  const Icon = PLAN_ICONS[plan.name]
  const titleId = `${audience}-${plan.name.toLowerCase()}`
  return <article className={`pub-plan${featured ? ' pub-plan--featured' : ''}`} aria-labelledby={titleId}>
    {featured && <span className="pub-plan__popular">Phổ biến nhất</span>}
    <div className="pub-plan__title"><span className="pub-plan__icon"><Icon size={24} strokeWidth={1.6} aria-hidden="true" /></span><h3 id={titleId}>{plan.name}</h3></div>
    <p className="pub-plan__description">{plan.description}</p>
    <p className="pub-plan__price">{plan.price === 0 ? 'Miễn phí' : <><span>{new Intl.NumberFormat('vi-VN').format(plan.price)}</span><small>VNĐ</small></>}</p>
    <div className="pub-plan__features">{plan.groups.map((group, index) => <div key={index}>{group.label && <h4>{group.label}</h4>}<ul>{group.features.map((feature) => <li key={feature}><Check size={16} aria-hidden="true" /><span>{feature}</span></li>)}</ul></div>)}</div>
    <div className="pub-plan__suitable"><h4>Phù hợp với:</h4><ul>{plan.suitableFor.map((item) => <li key={item}>{item}</li>)}</ul></div>
    <Link to={planSelectionPath(audience, plan.name)} className={`pub-button pub-plan__choose${featured ? ' pub-button--light' : ' pub-button--outline'}`} aria-label={`${plan.price === 0 ? 'Chọn gói' : 'Mua ngay'} ${plan.name} — ${audience === 'nong-ho' ? 'Nông hộ' : 'Hợp tác xã'}`}>{plan.price === 0 ? 'Chọn gói miễn phí' : 'Mua ngay'}</Link>
  </article>
}
