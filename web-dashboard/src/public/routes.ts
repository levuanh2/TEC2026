export const PUBLIC_NAV = [
  { to: '/nen-tang', label: 'Nền tảng' },
  { to: '/dich-vu', label: 'Dịch vụ' },
  { to: '/bao-cao', label: 'Báo cáo' },
  { to: '/bang-gia', label: 'Bảng giá' },
  { to: '/tin-tuc', label: 'Tin tức' },
] as const

export function isPublicPath(path: string): boolean {
  return path === '/' || PUBLIC_NAV.some((item) => item.to === path) || /^\/tin-tuc\/[^/]+$/.test(path)
}
