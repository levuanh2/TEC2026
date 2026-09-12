import type { Session } from '@supabase/supabase-js'
import { signOut } from '../../api/auth'
import type { CurrentUser } from '../../api/me'
import { getOrganization } from '../../api/organizations'
import { go, Link } from '../../ui'
import { initials } from '../activityView'
import { keys, STABLE_MS, useQuery } from '../data'
import { Ico } from '../icons'
import { Chip, Empty, ErrorPanel, IconTile, Section, Sk, SkBlock } from '../kit'
import { plotsOfFarm, seasonsOfPlots, useScope } from '../scope'

export function FarmerAccountPage({ session, viewer }: { session: Session | null; viewer: CurrentUser }) {
  const scope = useScope()
  const org = useQuery(viewer.organizationId ? keys.org(viewer.organizationId) : null, () => getOrganization(viewer.organizationId!), STABLE_MS)
  const email = session?.user.email ?? null
  const name = viewer.fullName?.trim() || null
  return (
    <>
      <section className="fw-account">
        <span className="fw-avatar fw-avatar--lg" aria-hidden="true">{initials(name, email)}</span>
        <div className="fw-account__id">
          <p className="fw-head__eyebrow"><Ico name="account" />Tài khoản</p>
          <h1>{name ?? email ?? 'Tài khoản nông hộ'}</h1>
          <div className="fw-account__chips">
            <Chip tone="leaf" icon="seeding">Vai trò: Nông hộ</Chip>
            {name && email && <Chip>{email}</Chip>}
            {org.data && <Chip tone="info" icon="farm">{org.data.name}</Chip>}
          </div>
        </div>
        <button type="button" className="fw-btn fw-btn--ghost" onClick={() => void signOut().then(() => go('/login'))}><Ico name="logout" />Đăng xuất</button>
      </section>

      <Section title="Phạm vi truy cập" icon="farm" description="Nông hộ, thửa ruộng và vụ canh tác mà tài khoản của bạn được cấp quyền xem và ghi.">
        {scope.loading ? (
          <SkBlock label="Đang tải phạm vi" className="fw-scope"><Sk h={96} r={18} /></SkBlock>
        ) : scope.error || !scope.data ? (
          <ErrorPanel error={scope.error ?? 'Không có dữ liệu.'} onRetry={scope.reload} />
        ) : !scope.data.farms.length ? (
          <Empty icon="farm" title="Chưa được cấp quyền nông hộ nào" body="Liên hệ quản lý HTX để được gán nông hộ hoặc thửa ruộng." />
        ) : (
          <div className="fw-scope">
            {scope.data.farms.map((farm) => {
              const plots = plotsOfFarm(scope.data!, farm.id)
              const seasons = seasonsOfPlots(scope.data!, plots)
              return (
                <div key={farm.id} className="fw-scope__farm">
                  <header>
                    <IconTile name="farm" tone="forest" size="sm" />
                    <span><b>{farm.name}</b><small>Mã hộ {farm.code} · {plots.length} thửa · {seasons.length} vụ</small></span>
                  </header>
                  {plots.length > 0 && (
                    <div className="fw-scope__plots">
                      {plots.map((p) => <Link key={p.id} to={`/farmer/plots/${p.id}`} className="fw-chip tone-leaf"><Ico name="plot" />{p.name}</Link>)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Section>

      <Section title="Về dữ liệu của bạn" icon="info" tone="info">
        <div className="fw-card fw-card--pad">
          <ul className="fw-bullets">
            <li><Ico name="check" />Bạn chỉ thấy các ruộng được cấp quyền; mọi dữ liệu được đọc qua phân quyền của tài khoản.</li>
            <li><Ico name="check" />Chỉ số và khuyến nghị chỉ tính từ dữ liệu bạn đã ghi; thiếu dữ liệu sẽ hiển thị “Chưa đủ dữ liệu”.</li>
          </ul>
        </div>
      </Section>
    </>
  )
}
