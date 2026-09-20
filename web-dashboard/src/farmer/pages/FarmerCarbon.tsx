import { Link } from '../../ui'
import { Empty } from '../kit'
import { HeroSkeleton } from './Home'
import { SeasonWorkspace } from './Season'
import { primarySeason, useScope } from '../scope'

/** `/farmer/carbon` — Carbon as a destination in the sidebar.
 *
 * A farmer thinks "Carbon", not "the Carbon tab of the season I happen to be
 * on", so the nav item resolves to the season they are working on and renders
 * the SAME workspace as `/farmer/crop-seasons/{id}/carbon`. No second screen,
 * no second data path, and the per-season URL keeps working unchanged.
 */
export function FarmerCarbonPage() {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  if (scope.loading) return <HeroSkeleton />
  if (!primary) {
    return (
      <Empty
        icon="carbon"
        title="Chưa có vụ đang canh tác để tính phát thải"
        body="Carbon được tính cho một vụ cụ thể. Chọn một vụ trong mục Ruộng / Vụ mùa để xem phần Carbon của vụ đó."
        action={<Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>}
      />
    )
  }
  return <SeasonWorkspace id={primary.season.id} tab="carbon" />
}
