import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronRight, ClipboardCheck, Download, Droplets, FileText, Leaf, MapPinned, Menu, Search, Sprout, Users, Wheat, X } from 'lucide-react'
import { Link } from '../ui'
import { ARTICLES, FEATURES, SERVICES, type PublicArticle } from './content'
import { PUBLIC_NAV } from './routes'
import './public.css'

const TITLES: Record<string, string> = { '/': 'Số hóa canh tác - Xanh hóa tương lai', '/nen-tang': 'Nền tảng', '/dich-vu': 'Dịch vụ', '/bao-cao': 'Báo cáo & tài liệu', '/bang-gia': 'Bảng giá', '/tin-tuc': 'Tin tức & kiến thức' }

function Logo() {
  return <Link to="/" className="pub-logo" aria-label="AgriCarbon — Trang chủ"><span className="pub-logo__mark"><Sprout size={27} strokeWidth={1.7} aria-hidden="true" /></span><span>AgriCarbon<small>GẮN KẾT DỮ LIỆU ĐỒNG RUỘNG</small></span></Link>
}

export function PublicSite({ path }: { path: string }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const article = ARTICLES.find((item) => path === `/tin-tuc/${item.slug}`)
  useEffect(() => {
    setMenuOpen(false)
    document.title = `AgriCarbon — ${article?.title ?? TITLES[path] ?? 'Bài viết'}`
    const scroll = requestAnimationFrame(() => {
      if (location.hash) {
        let id = location.hash.slice(1)
        try { id = decodeURIComponent(id) } catch { /* A malformed fragment must not break a public page. */ }
        document.getElementById(id)?.scrollIntoView()
      } else window.scrollTo({ top: 0, behavior: 'instant' })
    })
    return () => cancelAnimationFrame(scroll)
  }, [path, article])

  return (
    <div className="public-site" onKeyDown={(event) => { if (event.key === 'Escape' && menuOpen) { setMenuOpen(false); menuButton.current?.focus() } }}>
      <a className="skip-link" href="#public-main">Tới nội dung chính</a>
      <header className="pub-header">
        <div className="pub-header__inner">
          <Logo />
          <nav className={`pub-nav${menuOpen ? ' is-open' : ''}`} id="public-nav" aria-label="Điều hướng trang giới thiệu">
            {PUBLIC_NAV.map((item) => <Link to={item.to} key={item.to} aria-current={path === item.to || (item.to === '/tin-tuc' && Boolean(article)) ? 'page' : undefined} onClick={() => setMenuOpen(false)}>{item.label}</Link>)}
          </nav>
          <div className="pub-header__actions"><Link to="/login" className="pub-button pub-button--small">Đăng nhập <ArrowUpRight size={15} aria-hidden="true" /></Link><button ref={menuButton} type="button" className="pub-menu" aria-label={menuOpen ? 'Đóng menu giới thiệu' : 'Mở menu giới thiệu'} aria-expanded={menuOpen} aria-controls="public-nav" onClick={() => setMenuOpen((value) => !value)}>{menuOpen ? <X size={24} /> : <Menu size={24} />}</button></div>
        </div>
      </header>
      <main id="public-main" tabIndex={-1} key={path}>
        {path === '/' ? <Home /> : path === '/nen-tang' ? <Platform /> : path === '/dich-vu' ? <Services /> : path === '/bao-cao' ? <Reports /> : path === '/bang-gia' ? <Pricing /> : path === '/tin-tuc' ? <News /> : article ? <Article article={article} /> : <MissingArticle />}
      </main>
      <Footer />
    </div>
  )
}

function SectionHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description?: string; children?: ReactNode }) {
  return <div className="pub-section-heading"><div><p className="pub-eyebrow">{eyebrow}</p><h2>{title}</h2>{description && <p className="pub-section-description">{description}</p>}</div>{children}</div>
}

function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <section className="pub-page-heading"><div className="pub-container"><p className="pub-eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p><div className="pub-breadcrumb"><Link to="/">Trang chủ</Link><ChevronRight size={13} aria-hidden="true" /><span>{eyebrow}</span></div></div></section>
}

function Home() {
  return <>
    <section className="pub-hero" aria-labelledby="public-hero-title">
      <img className="pub-hero__image" src="/visuals/mekong-rice.webp" width="1536" height="1024" alt="" fetchPriority="high" />
      <div className="pub-hero__shade" />
      <div className="pub-hero__content"><p className="pub-eyebrow"><span /> CÔNG NGHỆ CHO NHỮNG MÙA VỤ XANH</p><h1 id="public-hero-title">Số hóa canh tác<span>Xanh hóa tương lai</span></h1><p className="pub-hero__intro">Từ mỗi thửa ruộng, kết nối dữ liệu canh tác với tài nguyên và carbon. Cùng nông hộ và hợp tác xã chăm chút từng mùa vụ.</p><div className="pub-hero__buttons"><Link to="/nen-tang" className="pub-button pub-button--light">Khám phá nền tảng <ArrowUpRight size={19} aria-hidden="true" /></Link><Link to="/login" className="pub-button pub-button--outline-light">Đăng nhập hệ thống <ArrowRight size={18} aria-hidden="true" /></Link></div><a className="pub-hero__scroll" href="#overview"><span>Khởi đầu từ dữ liệu trên ruộng</span><ArrowDown size={16} aria-hidden="true" /></a></div>
      <div className="pub-hero__landmark" aria-hidden="true"><Wheat size={30} strokeWidth={1.2} /><span>DÀNH CHO LÚA GẠO<br /><b>Gắn kết từ gốc rễ.</b></span></div>
      <span className="pub-hero__index" aria-hidden="true">AGRICARBON / TỪ ĐỒNG RUỘNG ĐẾN DỮ LIỆU</span>
    </section>
    <div className="pub-promise pub-container" id="overview"><span><BookOpen size={22} /><b>Ghi chép có hệ thống</b><small>Theo từng thửa, từng mùa vụ</small></span><span><Droplets size={22} /><b>Hiểu cách dùng tài nguyên</b><small>Đặt dữ liệu cạnh sản lượng</small></span><span><Leaf size={22} /><b>Theo dõi carbon minh bạch</b><small>Đọc cùng cơ sở phương pháp</small></span></div>
    <section className="pub-container pub-section"><SectionHeading eyebrow="MỘT NỀN TẢNG, NHIỀU KẾT NỐI" title="Nhìn rõ mùa vụ. Hiểu hơn đồng ruộng." description="Những ghi chép mỗi ngày trở thành dữ liệu có thể tra cứu, theo dõi và đối chiếu." /><FeatureGrid /><div className="pub-section-link"><Link to="/dich-vu">Khám phá các giải pháp <ArrowRight size={17} aria-hidden="true" /></Link></div></section>
    <section className="pub-workflow-section"><div className="pub-container pub-workflow-layout"><div><p className="pub-eyebrow">TỪ GHI NHẬN ĐẾN HÀNH ĐỘNG</p><h2>Mỗi bước nhỏ,<br />một kết nối lớn.</h2><p>Giữ dữ liệu theo cùng một mùa vụ, để người làm ruộng và người quản lý cùng hiểu điều đang diễn ra.</p><FieldDiagram /></div><Workflow /></div></section>
    <section className="pub-container pub-section"><SectionHeading eyebrow="ĐỒNG HÀNH CÙNG NGƯỜI SỬ DỤNG" title="Từ một nông hộ đến cả hợp tác xã." /><AudienceCards /></section>
    <section className="pub-container pub-section pub-home-news"><SectionHeading eyebrow="GÓC AGRICARBON" title="Hiểu thêm để bắt đầu tốt hơn."><Link to="/tin-tuc" className="pub-text-link">Tất cả bài viết <ArrowUpRight size={18} aria-hidden="true" /></Link></SectionHeading><div className="pub-news-grid">{ARTICLES.slice(0, 3).map((article) => <ArticleCard key={article.slug} article={article} />)}</div></section>
    <section className="pub-container pub-start"><div><p className="pub-eyebrow">BẮT ĐẦU TỪ MÙA VỤ CỦA BẠN</p><h2>Đưa dữ liệu đồng ruộng<br />về cùng một nơi.</h2><p>Khám phá phạm vi sử dụng phù hợp với nông hộ và đơn vị của bạn.</p></div><div className="pub-start__actions"><Link to="/bang-gia" className="pub-button pub-button--light">Xem phạm vi & bảng giá <ArrowUpRight size={18} aria-hidden="true" /></Link><Link to="/login" className="pub-start__login">Đã có tài khoản? Đăng nhập <ArrowRight size={16} aria-hidden="true" /></Link></div></section>
  </>
}

function FeatureGrid() {
  return <div className="pub-feature-grid">{FEATURES.map((item, index) => <div key={item.title} className={`pub-feature pub-tone-${item.tone}`}><div className="pub-feature__top"><span className="pub-icon"><item.icon size={24} strokeWidth={1.5} aria-hidden="true" /></span><span className="pub-feature__index">0{index + 1}</span></div><h3>{item.title}</h3><p>{item.description}</p></div>)}</div>
}

const STEPS = [
  { title: 'Ghi nhận', label: 'Những điều diễn ra trên ruộng', description: 'Tạo bối cảnh ruộng và vụ, sau đó ghi các lần gieo sạ, tưới nước, bón phân, xử lý rơm rạ và thu hoạch.', detail: 'Hoạt động gắn với ngày, lượng sử dụng và ghi chú.' },
  { title: 'Hiểu dữ liệu', label: 'Nhìn dữ liệu trong cùng bối cảnh', description: 'Xem tài nguyên và chi phí đã ghi cùng sản lượng. Kiểm tra dữ liệu còn thiếu trước khi đọc các chỉ số tổng hợp.', detail: 'Thiếu dữ liệu được thể hiện rõ, không mặc định là bằng không.' },
  { title: 'Hành động', label: 'Biết điều gì cần làm tiếp theo', description: 'Bổ sung dữ liệu, xem khuyến nghị hiện có và đối chiếu kết quả với tình trạng thực tế của mùa vụ.', detail: 'Kịch bản tham khảo được tách khỏi kết quả đã ghi nhận.' },
  { title: 'Báo cáo', label: 'Kết nối ghi chép với bằng chứng', description: 'Tổng hợp hồ sơ theo vụ, theo dõi tiến trình MRV và xuất báo cáo trong phạm vi được cấp quyền.', detail: 'Phần mềm hỗ trợ hồ sơ; thẩm định là một bước riêng.' },
]

function Workflow() {
  const [step, setStep] = useState(0)
  const buttons = useRef<(HTMLButtonElement | null)[]>([])
  return <div className="pub-workflow"><div className="pub-steps" role="tablist" aria-label="Các bước sử dụng AgriCarbon">{STEPS.map((item, index) => <button key={item.title} ref={(el) => { buttons.current[index] = el }} type="button" role="tab" aria-selected={step === index} aria-controls={`workflow-panel-${index}`} id={`workflow-tab-${index}`} tabIndex={step === index ? 0 : -1} onClick={() => setStep(index)} onKeyDown={(event) => { const next = event.key === 'ArrowRight' ? (index + 1) % STEPS.length : event.key === 'ArrowLeft' ? (index + STEPS.length - 1) % STEPS.length : event.key === 'Home' ? 0 : event.key === 'End' ? STEPS.length - 1 : null; if (next != null) { event.preventDefault(); setStep(next); buttons.current[next]?.focus() } }}><span>0{index + 1}</span>{item.title}</button>)}</div>{STEPS.map((item, index) => <div key={item.title} className="pub-step-panel" id={`workflow-panel-${index}`} role="tabpanel" aria-labelledby={`workflow-tab-${index}`} hidden={index !== step} tabIndex={0}><span className="pub-step-panel__number" aria-hidden="true">0{index + 1}</span><h3>{item.label}</h3><p>{item.description}</p><div className="pub-step-panel__detail"><Check size={17} aria-hidden="true" />{item.detail}</div></div>)}</div>
}

function FieldDiagram() {
  return <div className="pub-field-diagram" aria-hidden="true"><svg viewBox="0 0 480 180" fill="none"><path d="M15 125 95 35l110 22-73 94Z" fill="#aecb85" /><path d="m111 25 73-15 102 37-65 10Z" fill="#e8d28f" /><path d="m150 157 74-89 98 33-56 70Z" fill="#d0dea3" /><path d="m245 61 61-16 146 52-98 5Z" fill="#72a587" /><path d="m288 172 59-63 106 4-31 65Z" fill="#93bf9c" /><path d="M96 6c-23 34 21 44 66 46 116 8 156 63 134 127" stroke="#c5e6df" strokeWidth="8" /><path d="m32 127 65-70m-45 80 65-72m-41 82 65-74m31 75 53-62m-28 71 53-62m-26 70 53-60m37 72 43-48m-13 54 43-47" stroke="#f9fbec" strokeOpacity=".5" strokeWidth="2" /></svg><span>THỬA RUỘNG → MÙA VỤ → DỮ LIỆU</span></div>
}

function AudienceCards() {
  return <div className="pub-audience-grid"><div className="pub-audience pub-audience--farmer"><span className="pub-icon"><Sprout size={25} aria-hidden="true" /></span><p className="pub-eyebrow">CHO NÔNG HỘ</p><h3>Một cuốn nhật ký,<br />theo sát từng mùa vụ.</h3><p>Ghi chép công việc, xem mùa vụ đang canh tác và biết dữ liệu nào cần bổ sung.</p><a href="/dich-vu#nhat-ky" className="pub-text-link">Tìm hiểu cho nông hộ <ArrowRight size={18} aria-hidden="true" /></a></div><div className="pub-audience pub-audience--coop"><span className="pub-icon"><Users size={25} aria-hidden="true" /></span><p className="pub-eyebrow">CHO HỢP TÁC XÃ & ĐƠN VỊ THEO DÕI</p><h3>Một không gian chung,<br />kết nối nhiều nông hộ.</h3><p>Theo dõi dữ liệu theo cấp nông hộ, thửa và vụ; tổng hợp công việc và hồ sơ trong phạm vi được giao.</p><a href="/dich-vu#hop-tac-xa" className="pub-text-link">Tìm hiểu cho đơn vị <ArrowRight size={18} aria-hidden="true" /></a></div></div>
}

function Platform() {
  return <><PageHeading eyebrow="NỀN TẢNG AGRICARBON" title="Dữ liệu đồng ruộng, kết nối liền mạch." description="Một nơi để ghi nhận canh tác, đọc hiệu suất tài nguyên và theo dõi carbon theo từng mùa vụ lúa." /><section className="pub-container pub-section"><SectionHeading eyebrow="NHỮNG KẾT NỐI CỐT LÕI" title="Từ hoạt động mỗi ngày đến bức tranh mùa vụ." /><FeatureGrid /></section><section className="pub-workflow-section"><div className="pub-container pub-workflow-layout"><div><p className="pub-eyebrow">CÁCH NỀN TẢNG HOẠT ĐỘNG</p><h2>Đi cùng dữ liệu,<br />qua từng bước.</h2><p>Chọn từng bước để tìm hiểu cách sử dụng.</p><FieldDiagram /></div><Workflow /></div></section><section className="pub-container pub-section"><AudienceCards /><div className="pub-note"><Leaf size={20} aria-hidden="true" /><p>Kết quả carbon phụ thuộc vào dữ liệu đầu vào và cơ sở phương pháp. AgriCarbon hiển thị điều kiện, giới hạn và trạng thái dữ liệu để người dùng đọc kết quả trong đúng bối cảnh.</p></div></section></>
}

function Services() {
  return <><PageHeading eyebrow="DỊCH VỤ & GIẢI PHÁP" title="Đúng công cụ, đúng việc trên ruộng." description="Khám phá các nhóm chức năng hỗ trợ nông hộ, hợp tác xã và đơn vị được phân quyền theo dõi dữ liệu." /><section className="pub-container pub-section"><div className="pub-services-grid">{SERVICES.map((item) => <section className={`pub-service pub-tone-${item.tone}`} id={item.id} key={item.id}><span className="pub-icon"><item.icon size={25} aria-hidden="true" /></span><p className="pub-eyebrow">{item.audience}</p><h2>{item.title}</h2><p>{item.description}</p><ul>{item.points.map((point) => <li key={point}><Check size={16} aria-hidden="true" />{point}</li>)}</ul><Link to="/login" className="pub-text-link">Đăng nhập để sử dụng <ArrowUpRight size={17} aria-hidden="true" /></Link></section>)}</div><div className="pub-note"><ClipboardCheck size={21} aria-hidden="true" /><p>Chức năng hiển thị theo vai trò và phạm vi của tài khoản. AgriCarbon hỗ trợ quản lý dữ liệu và hồ sơ; việc thẩm định, chứng nhận hoặc phát hành tín chỉ carbon được thực hiện ngoài phạm vi phần mềm.</p></div></section></>
}

function Reports() {
  return <><PageHeading eyebrow="BÁO CÁO & TÀI LIỆU" title="Hiểu dữ liệu. Chuẩn bị hồ sơ." description="Tài liệu giới thiệu và biểu mẫu để bắt đầu tổ chức dữ liệu canh tác cùng AgriCarbon." /><section className="pub-container pub-section"><div className="pub-resource-grid"><Resource icon={<FileText size={29} />} type="GIỚI THIỆU · MARKDOWN" title="Tổng quan nền tảng AgriCarbon" description="Các nhóm chức năng, đối tượng sử dụng và nguyên tắc đọc dữ liệu trong nền tảng." href="/downloads/agricarbon-gioi-thieu.md" label="Tải bản giới thiệu" /><Resource icon={<BookOpen size={29} />} type="BIỂU MẪU · CSV" title="Mẫu chuẩn bị nhật ký canh tác" description="Bảng trống để chuẩn bị ngày thực hiện, hoạt động, lượng sử dụng và đơn vị trước khi ghi vào hệ thống." href="/downloads/agricarbon-mau-nhat-ky.csv" label="Tải biểu mẫu CSV" /><div className="pub-resource pub-resource--green"><span className="pub-icon"><ClipboardCheck size={29} /></span><p className="pub-eyebrow">HỒ SƠ TRONG HỆ THỐNG</p><h2>Báo cáo của vụ mùa của bạn</h2><p>Đăng nhập để xem dữ liệu được cấp quyền. Người quản lý có thể theo dõi hồ sơ và xuất báo cáo từ dữ liệu trong hệ thống.</p><Link to="/login" className="pub-text-link">Đăng nhập hệ thống <ArrowRight size={18} aria-hidden="true" /></Link></div></div><div className="pub-note"><FileText size={21} aria-hidden="true" /><p>Các tệp tải tại đây là tài liệu giới thiệu và biểu mẫu chuẩn bị dữ liệu, không phải báo cáo phát thải thực tế, mẫu thẩm định chính thức hoặc chứng nhận carbon.</p></div><SectionHeading eyebrow="ĐỌC THÊM" title="Từ dữ liệu đến hồ sơ có thể đối chiếu." /><div className="pub-news-grid">{ARTICLES.filter((article) => article.category === 'Carbon & MRV' || article.category === 'Tài nguyên').map((article) => <ArticleCard key={article.slug} article={article} />)}</div></section></>
}

function Resource({ icon, type, title, description, href, label }: { icon: ReactNode; type: string; title: string; description: string; href: string; label: string }) {
  return <div className="pub-resource"><span className="pub-icon" aria-hidden="true">{icon}</span><p className="pub-eyebrow">{type}</p><h2>{title}</h2><p>{description}</p><a className="pub-text-link" href={href} download>{label}<Download size={17} aria-hidden="true" /></a></div>
}

function Pricing() {
  const plans = [
    { audience: 'Nông hộ', icon: Sprout, title: 'Theo sát mùa vụ', text: 'Dành cho việc ghi chép và đọc dữ liệu tại ruộng.', points: ['Nhật ký theo thửa và vụ', 'Theo dõi tài nguyên đã ghi', 'Xem dữ liệu và khuyến nghị trong phạm vi tài khoản'], to: '/dich-vu#nhat-ky' },
    { audience: 'Hợp tác xã', icon: Users, title: 'Kết nối nhiều nông hộ', text: 'Dành cho tổ chức điều phối và quản lý dữ liệu.', points: ['Tổng hợp nông hộ, thửa và vụ', 'Theo dõi dữ liệu thiếu và công việc', 'Quản lý hồ sơ MRV theo phân quyền'], to: '/dich-vu#hop-tac-xa' },
    { audience: 'Đơn vị theo dõi', icon: MapPinned, title: 'Đọc dữ liệu có bối cảnh', text: 'Dành cho đơn vị được cấp quyền tiếp cận dữ liệu.', points: ['Xem dữ liệu theo phạm vi được giao', 'Theo dõi chỉ số và tình trạng hồ sơ', 'Phân biệt kết quả, giới hạn và dữ liệu thiếu'], to: '/nen-tang' },
  ]
  return <><PageHeading eyebrow="PHẠM VI SỬ DỤNG & BẢNG GIÁ" title="Giải pháp theo quy mô của bạn." description="Từ một nông hộ đến đơn vị quản lý nhiều mùa vụ, chọn phạm vi sử dụng để tìm hiểu chức năng phù hợp." /><section className="pub-container pub-section"><div className="pub-pricing-status"><span><Leaf size={19} aria-hidden="true" /> Chính sách giá đang được hoàn thiện</span><p>AgriCarbon chưa công bố giá. Các phạm vi bên dưới giúp bạn tìm hiểu chức năng, chưa phải gói dịch vụ thương mại hoặc cam kết cung cấp.</p></div><div className="pub-pricing-grid">{plans.map((plan, index) => <div key={plan.audience} className={`pub-plan${index === 1 ? ' pub-plan--featured' : ''}`}><div className="pub-plan__audience"><plan.icon size={23} aria-hidden="true" /><span>{plan.audience}</span></div><h2>{plan.title}</h2><p>{plan.text}</p><div className="pub-plan__price"><span>Chưa công bố giá</span><small>Thông tin sẽ được cập nhật tại đây</small></div><ul>{plan.points.map((point) => <li key={point}><Check size={16} aria-hidden="true" />{point}</li>)}</ul><Link to={plan.to} className={`pub-button${index === 1 ? '' : ' pub-button--outline'}`}>Xem chức năng phù hợp <ArrowUpRight size={16} aria-hidden="true" /></Link></div>)}</div><div className="pub-pricing-help"><h2>Bạn đã có tài khoản AgriCarbon?</h2><p>Tiếp tục sử dụng không gian đã được cấp quyền cho bạn.</p><Link to="/login" className="pub-text-link">Đăng nhập hệ thống <ArrowRight size={17} aria-hidden="true" /></Link></div></section></>
}

function ArticleCard({ article }: { article: PublicArticle }) {
  return <article className="pub-article-card"><Link to={`/tin-tuc/${article.slug}`} className="pub-article-card__link"><div className={`pub-article-art pub-tone-${article.tone}`} aria-hidden="true"><article.icon size={55} strokeWidth={1.1} /><span className="pub-article-art__line" /><span>GÓC AGRICARBON</span></div><div className="pub-article-card__body"><div className="pub-article-meta"><span>{article.category}</span><span>{article.time}</span></div><h3>{article.title}</h3><p>{article.excerpt}</p><span className="pub-article-card__more">Đọc bài viết <ArrowUpRight size={17} aria-hidden="true" /></span></div></Link></article>
}

function News() {
  const [category, setCategory] = useState('Tất cả')
  const [search, setSearch] = useState('')
  const categories = ['Tất cả', ...new Set(ARTICLES.map((article) => article.category))]
  const query = search.trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('vi')
  const articles = ARTICLES.filter((article) => (category === 'Tất cả' || article.category === category) && `${article.title} ${article.excerpt}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('vi').includes(query))
  return <><PageHeading eyebrow="TIN TỨC & KIẾN THỨC" title="Góc nhìn từ đồng ruộng và dữ liệu." description="Bài viết hướng dẫn do nhóm AgriCarbon biên soạn, giúp bạn hiểu nền tảng và chuẩn bị dữ liệu canh tác." /><section className="pub-container pub-section"><div className="pub-news-tools"><div className="pub-news-filters" aria-label="Lọc chuyên mục">{categories.map((item) => <button type="button" key={item} aria-pressed={category === item} onClick={() => setCategory(item)}>{item}</button>)}</div><label className="pub-news-search"><Search size={18} aria-hidden="true" /><span className="sr-only">Tìm bài viết</span><input type="search" placeholder="Tìm bài viết…" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div><p className="pub-news-count" role="status">{articles.length} bài viết</p>{articles.length ? <div className="pub-news-grid">{articles.map((article) => <ArticleCard key={article.slug} article={article} />)}</div> : <div className="pub-news-empty"><BookOpen size={35} aria-hidden="true" /><h2>Chưa tìm thấy bài viết phù hợp</h2><p>Thử từ khóa hoặc chuyên mục khác.</p><button type="button" className="pub-button pub-button--outline" onClick={() => { setSearch(''); setCategory('Tất cả') }}>Xem tất cả bài viết</button></div>}</section></>
}

function Article({ article }: { article: PublicArticle }) {
  return <><PageHeading eyebrow={article.category} title={article.title} description={article.excerpt} /><article className="pub-article pub-container"><div className="pub-article__meta"><span><Sprout size={16} aria-hidden="true" /> Nhóm AgriCarbon</span><span>{article.time}</span><span>Kiến thức sử dụng</span></div><div className={`pub-article-hero pub-tone-${article.tone}`} aria-hidden="true"><article.icon size={70} strokeWidth={1.1} /><FieldDiagram /></div>{article.sections.map((section) => <section key={section.title}><h2>{section.title}</h2><p>{section.body}</p></section>)}<div className="pub-article__end"><Link to="/tin-tuc" className="pub-text-link">← Tất cả bài viết</Link><Link to="/login" className="pub-button">Đăng nhập AgriCarbon <ArrowUpRight size={17} aria-hidden="true" /></Link></div></article></>
}

function MissingArticle() {
  return <div className="pub-container pub-news-empty"><BookOpen size={38} aria-hidden="true" /><h1>Không tìm thấy bài viết</h1><p>Bài viết có thể đã được chuyển hoặc đường dẫn chưa chính xác.</p><Link to="/tin-tuc" className="pub-button">Về trang Tin tức</Link></div>
}

function Footer() {
  return <footer className="pub-footer"><div className="pub-container pub-footer__main"><div className="pub-footer__brand"><Logo /><p>Số hóa canh tác - Xanh hóa tương lai</p><span>Nền tảng dữ liệu canh tác lúa gạo,<br />tài nguyên và carbon.</span></div><div><h2>Khám phá AgriCarbon</h2><nav aria-label="Liên kết cuối trang">{PUBLIC_NAV.map((item) => <Link to={item.to} key={item.to}>{item.label}</Link>)}</nav></div><div><h2>Dành cho bạn</h2><a href="/dich-vu#nhat-ky">Nông hộ</a><a href="/dich-vu#hop-tac-xa">Hợp tác xã & đơn vị theo dõi</a><Link to="/bao-cao">Tài liệu bắt đầu</Link><Link to="/login">Đăng nhập hệ thống <ArrowUpRight size={14} aria-hidden="true" /></Link></div></div><div className="pub-container pub-footer__bottom"><span>© {new Date().getFullYear()} AgriCarbon.</span><span>Chăm từng mùa vụ. Vun đắp tương lai xanh.</span></div></footer>
}
