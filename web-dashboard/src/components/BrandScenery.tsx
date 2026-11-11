import type { ReactNode } from 'react'
import { Droplets, Leaf, Sprout, Wheat } from 'lucide-react'

export const BRAND_SLOGAN = 'Số hóa canh tác - Xanh hóa tương lai'

/** Decorative brand artwork; it never represents a user's farm or live data. */
export function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><Sprout size={25} strokeWidth={1.7} /></span>
}

export function AuthScenery({ children }: { children: ReactNode }) {
  return (
    <main className="login login--scenic">
      <aside className="login-landscape" aria-label="AgriCarbon — Số hóa canh tác - Xanh hóa tương lai">
        <img className="login-landscape__image" src="/visuals/mekong-rice.webp" alt="" fetchPriority="high" />
        <div className="login-landscape__veil" />
        <div className="login-landscape__brand"><BrandMark /><span>AgriCarbon<small>NÔNG NGHIỆP &amp; TƯƠNG LAI XANH</small></span></div>
        <div className="login-landscape__story">
          <span className="login-landscape__eyebrow"><span /> TỪ ĐỒNG RUỘNG, ĐẾN TƯƠNG LAI</span>
          <p className="login-slogan"><span>Số hóa canh tác</span><span>Xanh hóa tương lai</span></p>
          <p className="login-landscape__description">Kết nối nhật ký đồng ruộng, theo dõi tài nguyên và quản lý carbon trong một không gian.</p>
          <div className="login-landscape__topics"><span><Sprout size={17} /> Canh tác</span><span><Droplets size={17} /> Tài nguyên</span><span><Leaf size={17} /> Carbon</span></div>
        </div>
        <div className="login-landscape__foot"><span>Gắn kết dữ liệu. Đồng hành cùng nhà nông.</span><Wheat size={28} aria-hidden="true" /></div>
        <div className="field-ripple field-ripple--one" aria-hidden="true" />
        <div className="field-ripple field-ripple--two" aria-hidden="true" />
      </aside>
      <div className="login-workspace">
        {children}
        <p className="login-workspace__foot"><Leaf size={14} aria-hidden="true" />{BRAND_SLOGAN}</p>
      </div>
    </main>
  )
}

export function FieldBanner({ farmer = false }: { farmer?: boolean }) {
  return (
    <div className="field-banner">
      <div className="field-banner__copy">
        <p className="field-banner__eyebrow"><Sprout size={15} aria-hidden="true" /> AGRICARBON / {farmer ? 'ĐỒNG HÀNH CÙNG NÔNG HỘ' : 'KẾT NỐI HỢP TÁC XÃ'}</p>
        <p className="field-banner__title">Số hóa canh tác <span>- Xanh hóa tương lai</span></p>
        <p className="field-banner__sub">{farmer ? 'Chăm từng mùa vụ, vun đắp tương lai xanh.' : 'Từ dữ liệu đồng ruộng đến những quyết định có cơ sở.'}</p>
      </div>
      <div className="field-banner__art" aria-hidden="true"><img src="/visuals/mekong-rice.webp" alt="" /></div>
    </div>
  )
}
