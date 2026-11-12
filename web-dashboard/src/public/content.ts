import { BookOpen, ChartNoAxesCombined, ClipboardCheck, Droplets, Leaf, ScanLine } from 'lucide-react'

export const FEATURES = [
  { icon: BookOpen, title: 'Nhật ký từ đồng ruộng', description: 'Gieo sạ, bón phân, tưới nước, thu hoạch — ghi nhận từng hoạt động theo đúng thửa ruộng và vụ mùa.', tone: 'leaf' },
  { icon: Droplets, title: 'Hiểu cách dùng tài nguyên', description: 'Theo dõi nước, phân bón và chi phí cùng với sản lượng để đọc hiệu suất trên mỗi kg lúa.', tone: 'water' },
  { icon: Leaf, title: 'Dữ liệu làm rõ carbon', description: 'Xem kết quả tính, dữ liệu còn thiếu và cơ sở phương pháp; phân biệt kết quả đã ghi nhận với kịch bản tham khảo.', tone: 'carbon' },
  { icon: ClipboardCheck, title: 'Kết nối hồ sơ MRV', description: 'Tập hợp hoạt động, bằng chứng và báo cáo theo vụ để hỗ trợ quy trình đo đạc, báo cáo và thẩm định.', tone: 'grain' },
] as const

export const SERVICES = [
  { ...FEATURES[0], id: 'nhat-ky', audience: 'Cho nông hộ', points: ['Quản lý ruộng, thửa và vụ mùa', 'Ghi chép các hoạt động canh tác', 'Tra cứu nhật ký trong cùng một nơi'] },
  { ...FEATURES[1], id: 'tai-nguyen', audience: 'Cho nông hộ & hợp tác xã', points: ['Đọc chỉ số theo vụ và sản lượng', 'Nhận biết dữ liệu cần bổ sung', 'Theo dõi chi phí trực tiếp đã ghi'] },
  { ...FEATURES[2], id: 'carbon', audience: 'Cho người quản lý dữ liệu', points: ['Kiểm tra điều kiện trước khi tính', 'Xem nguồn hệ số và kết quả', 'Theo dõi kết quả cần tính lại'] },
  { ...FEATURES[3], id: 'mrv', audience: 'Cho hợp tác xã', points: ['Theo dõi tiến trình hồ sơ', 'Quản lý bằng chứng theo vụ', 'Xuất báo cáo trong hệ thống'] },
  { icon: ScanLine, title: 'Kiểm tra lá lúa bằng ảnh', description: 'Ảnh chụp hỗ trợ nhận diện dấu hiệu trên lá lúa và xem mức độ tin cậy của mô hình.', tone: 'leaf', id: 'kiem-tra-la', audience: 'Hỗ trợ quan sát tại ruộng', points: ['Chọn ảnh và xem kết quả tham khảo', 'Thông báo khi mô hình chưa chắc chắn', 'Cần đối chiếu với tình trạng thực tế'] },
  { icon: ChartNoAxesCombined, title: 'Không gian quản lý hợp tác xã', description: 'Kết nối dữ liệu từ nhiều nông hộ theo phạm vi được phân quyền, giúp người quản lý theo dõi công việc cần xử lý.', tone: 'water', id: 'hop-tac-xa', audience: 'Cho hợp tác xã & đơn vị theo dõi', points: ['Tổng hợp nông hộ, thửa và mùa vụ', 'Theo dõi dữ liệu thiếu và trạng thái carbon', 'Phân quyền truy cập theo vai trò'] },
] as const

export const ARTICLES = [
  {
    slug: 'nhat-ky-canh-tac-bat-dau-tu-dau', category: 'Nhật ký canh tác', time: '4 phút đọc', tone: 'leaf', icon: BookOpen,
    title: 'Một mùa vụ rõ ràng bắt đầu từ những ghi chép nhỏ',
    excerpt: 'Ghi gì, ghi vào đâu và làm thế nào để nhật ký theo sát công việc trên ruộng?',
    sections: [
      { title: 'Bắt đầu từ đúng ruộng và đúng vụ', body: 'Một lần ghi chép có ích khi bạn biết nó thuộc thửa ruộng và vụ nào. Trước khi nhập hoạt động, hãy kiểm tra tên vụ, thửa và ngày thực hiện. Điều này giúp việc tra cứu và tổng hợp sau này có cùng một bối cảnh.' },
      { title: 'Ghi theo hoạt động thực tế', body: 'AgriCarbon hỗ trợ ghi gieo sạ, bón phân, tưới nước, thuốc bảo vệ thực vật, quản lý rơm rạ và thu hoạch. Hãy ghi lượng sử dụng cùng đơn vị phù hợp. Chi phí, ghi chú và thông tin bổ sung giúp bạn hiểu đầy đủ hơn việc đã làm.' },
      { title: 'Kiểm tra lại sau khi ghi', body: 'Mở nhật ký để đối chiếu ngày, loại hoạt động và lượng đã nhập. Nếu cần chỉnh sửa, hãy sửa bản ghi tương ứng thay vì tạo thêm một bản trùng. Các thao tác phụ thuộc vào quyền truy cập và trạng thái vụ.' },
    ],
  },
  {
    slug: 'hieu-suat-tai-nguyen-tren-moi-kg-lua', category: 'Tài nguyên', time: '3 phút đọc', tone: 'water', icon: Droplets,
    title: 'Hiểu tài nguyên trên mỗi kg lúa, thay vì chỉ nhìn tổng lượng',
    excerpt: 'Kết nối nước, phân bón và chi phí với sản lượng để đọc dữ liệu trong cùng một bối cảnh.',
    sections: [
      { title: 'Tổng lượng và chỉ số theo sản lượng', body: 'Tổng lượng nước hoặc phân bón cho biết lượng đã ghi nhận trong vụ. Chỉ số trên mỗi kg sản phẩm đặt lượng đó cạnh sản lượng thu hoạch. Hai cách nhìn bổ sung cho nhau; mỗi cách trả lời một câu hỏi khác nhau.' },
      { title: 'Thiếu dữ liệu không có nghĩa là bằng không', body: 'Nếu vụ chưa có sản lượng hoặc thiếu hoạt động liên quan, chỉ số có thể chưa tính được. Hãy đọc thông báo dữ liệu còn thiếu. Một ô chưa đủ dữ liệu không nên được hiểu là không sử dụng tài nguyên hay không phát sinh chi phí.' },
      { title: 'Đọc cùng phạm vi và điều kiện', body: 'Trước khi so sánh, hãy xem lại vụ, diện tích, thời điểm ghi và mức độ đầy đủ của nhật ký. Chi phí trong nền tảng là chi phí trực tiếp đã ghi; các khoản chưa nhập sẽ chưa xuất hiện trong phần tổng hợp.' },
    ],
  },
  {
    slug: 'du-lieu-canh-tac-va-ho-so-mrv', category: 'Carbon & MRV', time: '4 phút đọc', tone: 'grain', icon: ClipboardCheck,
    title: 'Từ nhật ký đồng ruộng đến hồ sơ có thể đối chiếu',
    excerpt: 'Hoạt động, bằng chứng và kết quả tính cần được đặt cạnh nhau như thế nào?',
    sections: [
      { title: 'Một hồ sơ cần dữ liệu có bối cảnh', body: 'Ngày thực hiện, hoạt động, lượng vật tư và vụ mùa giúp người đọc hiểu dữ liệu đến từ đâu. Bằng chứng đi kèm hỗ trợ việc đối chiếu giữa ghi chép và thực tế. AgriCarbon tập hợp các phần này theo phạm vi được cấp quyền.' },
      { title: 'Kết quả tính đi cùng cơ sở phương pháp', body: 'Một kết quả carbon cần được đọc cùng dữ liệu đầu vào, hệ số, phiên bản phương pháp và các giới hạn được công bố trong hệ thống. Nếu dữ liệu thay đổi, cần kiểm tra kết quả có còn phù hợp hay phải tính lại.' },
      { title: 'Hỗ trợ báo cáo và thẩm định', body: 'Nền tảng hỗ trợ quản lý tiến trình và xuất hồ sơ. Báo cáo phần mềm không tự thay thế việc thẩm định độc lập, xác minh thực địa hoặc cấp tín chỉ carbon. Những bước đó cần được thực hiện theo yêu cầu của đơn vị có thẩm quyền.' },
    ],
  },
  {
    slug: 'kiem-tra-la-lua-bang-anh', category: 'Góc sử dụng', time: '3 phút đọc', tone: 'carbon', icon: ScanLine,
    title: 'Một bức ảnh lá lúa hữu ích cần những gì?',
    excerpt: 'Chụp rõ một lá, đủ sáng và hiểu thông báo khi mô hình chưa đủ tin cậy.',
    sections: [
      { title: 'Chọn ảnh có chủ thể rõ', body: 'Đặt một lá lúa làm chủ thể chính, chụp đủ sáng và kiểm tra ảnh không bị nhòe. Tránh để nền rối hoặc nhiều lá che lẫn nhau. Bạn có thể xem lại ảnh trước khi yêu cầu phân tích.' },
      { title: 'Đọc cả kết quả và độ tin cậy', body: 'Mô hình có thể trả về thông báo chưa đủ tin cậy để gán nhãn. Trong trường hợp đó, hãy thử ảnh rõ hơn thay vì xem thông báo như một kết luận về tình trạng cây. Kết quả là thông tin tham khảo và cần được đối chiếu thực tế.' },
      { title: 'Giữ bối cảnh quan sát tại ruộng', body: 'Ảnh chỉ phản ánh một phần tình trạng cây tại thời điểm chụp. Quan sát thêm các cây xung quanh và trao đổi với người có chuyên môn khi cần. Tránh đưa ra quyết định xử lý chỉ dựa trên một kết quả từ ảnh.' },
    ],
  },
] as const

export type PublicArticle = (typeof ARTICLES)[number]
