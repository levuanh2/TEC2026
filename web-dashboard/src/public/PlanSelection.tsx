import { useEffect } from 'react'
import { Check, Sprout } from 'lucide-react'
import { Link } from '../ui'
import { readPlanSelection } from './pricing'
import './public.css'

/** Mounted by AppRoot only after the existing session/role/password gates. */
export function PlanSelectionPage({ home }: { home: string }) {
  const selection = readPlanSelection(location.search)
  useEffect(() => { document.title = 'AgriCarbon — Gói dịch vụ đã chọn' }, [])
  return <div className="public-site"><main className="pub-container pub-section pub-selection">
    <Link to="/bang-gia" className="pub-text-link">← Quay lại bảng giá</Link>
    <p className="pub-eyebrow"><Sprout size={20} aria-hidden="true" /> AGRICARBON</p>
    <h1>{selection ? 'Gói dịch vụ bạn đã chọn' : 'Chưa chọn gói hợp lệ'}</h1>
    {selection ? <>
      <section className="pub-selection__summary" aria-label="Thông tin gói đã chọn">
        <p>{selection.audienceLabel}</p><h2>Gói {selection.plan.name}</h2>
        <p className="pub-selection__price">{selection.plan.price === 0 ? 'Miễn phí' : `${new Intl.NumberFormat('vi-VN').format(selection.plan.price)} VNĐ`}</p>
        <p>{selection.plan.description}</p>
        <ul>{selection.plan.groups.flatMap((group) => group.features).map((feature) => <li key={feature}><Check size={17} aria-hidden="true" /><span>{feature}</span></li>)}</ul>
      </section>
      <p className="pub-selection__notice" role="status">Bạn đã chọn gói {selection.plan.name}. Chưa phát sinh thanh toán hoặc kích hoạt dịch vụ.</p>
    </> : <p>Vui lòng quay lại bảng giá để chọn gói Nông hộ hoặc Hợp tác xã.</p>}
    <div className="pub-selection__actions"><Link to="/bang-gia" className="pub-button pub-button--outline">{selection ? 'Chọn gói khác' : 'Xem bảng giá'}</Link><Link to={home} className="pub-button">Vào không gian của tôi</Link></div>
  </main></div>
}
