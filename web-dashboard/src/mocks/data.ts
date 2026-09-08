import type { Activity, CropSeason, Farm, Plot } from '../types'
// MOCK DATA — NOT PRODUCTION. Used only until FastAPI hierarchy endpoints exist.
export const farms: Farm[] = [{ id: 'farm-demo-01', code: 'HH-001', name: 'Nguyễn Văn An', province: 'Đồng Tháp', district: 'Tháp Mười', commune: 'Tân Phú', plotCount: 2, areaHa: 4.2 }]
export const plots: Plot[] = [{ id: 'plot-demo-01', farmId: 'farm-demo-01', code: 'A-01', name: 'Thửa A-01', areaHa: 1.42, location: 'Đồng Tháp' }]
export const cropSeasons: CropSeason[] = [{ id: 'crop-demo-01', plotId: 'plot-demo-01', name: 'Hè Thu 2026', variety: 'OM5451', plantingDate: '2026-05-18', status: 'Đang canh tác', totalYieldKg: null }]
export const activities: Activity[] = [{ id: 'act-demo-01', cropSeasonId: 'crop-demo-01', occurredAt: '2026-09-02 06:30', type: 'irrigation', detail: 'Tưới AWD · 32 mm', recorder: 'Nguyễn Văn An', source: 'Mobile offline' }]
