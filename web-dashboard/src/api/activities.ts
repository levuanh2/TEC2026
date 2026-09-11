// Farmer Web online activity writes (FW-2 Part 2). Field names/shape mirror
// the frozen runtime contract in backend/schemas.py exactly — verified against
// backend/api.py + backend/service.py, not against prior prose.
import { apiRequest } from './client'

export type IrrigationMethod = 'awd' | 'continuous_flooding' | 'alternate' | 'other'

export interface FertilizerActivityInput {
  fertilizerName: string
  fertilizerType?: string | null
  amountKg: number
  nitrogenPercent?: number | null
  phosphorusPercent?: number | null
  potassiumPercent?: number | null
  totalCostVnd?: number | null
}

export interface IrrigationActivityInput {
  method: IrrigationMethod
  // Blank must stay `null`, never an invented 0 (brief FW-2 §12).
  waterVolumeM3?: number | null
  durationMinutes?: number | null
  waterLevelCm?: number | null
  pumpEnergyKwh?: number | null
  totalCostVnd?: number | null
}

export interface HarvestActivityInput {
  yieldKg: number
  harvestedAreaHa?: number | null
  moisturePercent?: number | null
  totalCostVnd?: number | null
}

export type ActivityInput =
  | { activityType: 'fertilizer'; data: FertilizerActivityInput }
  | { activityType: 'irrigation'; data: IrrigationActivityInput }
  | { activityType: 'harvest'; data: HarvestActivityInput }

export type SupportedActivityType = ActivityInput['activityType']

export interface ActivityWriteResult {
  id: string
  cropSeasonId: string
  activityType: SupportedActivityType
  occurredAt: string
  note: string | null
  data: Record<string, unknown>
  createdBy: string
  createdAt: string
  updatedAt: string
  idempotentReplay: boolean
}

function fertilizerPayload(input: FertilizerActivityInput): Record<string, unknown> {
  return {
    fertilizer_name: input.fertilizerName,
    fertilizer_type: input.fertilizerType ?? null,
    amount_kg: input.amountKg,
    nitrogen_percent: input.nitrogenPercent ?? null,
    phosphorus_percent: input.phosphorusPercent ?? null,
    potassium_percent: input.potassiumPercent ?? null,
    total_cost_vnd: input.totalCostVnd ?? null,
  }
}

function irrigationPayload(input: IrrigationActivityInput): Record<string, unknown> {
  return {
    method: input.method,
    water_volume_m3: input.waterVolumeM3 ?? null,
    duration_minutes: input.durationMinutes ?? null,
    water_level_cm: input.waterLevelCm ?? null,
    pump_energy_kwh: input.pumpEnergyKwh ?? null,
    total_cost_vnd: input.totalCostVnd ?? null,
  }
}

function harvestPayload(input: HarvestActivityInput): Record<string, unknown> {
  return {
    yield_kg: input.yieldKg,
    harvested_area_ha: input.harvestedAreaHa ?? null,
    moisture_percent: input.moisturePercent ?? null,
    total_cost_vnd: input.totalCostVnd ?? null,
  }
}

export function activityDataPayload(input: ActivityInput): Record<string, unknown> {
  switch (input.activityType) {
    case 'fertilizer': return fertilizerPayload(input.data)
    case 'irrigation': return irrigationPayload(input.data)
    case 'harvest': return harvestPayload(input.data)
  }
}

const mapWriteResult = (x: any): ActivityWriteResult => ({
  id: x.id,
  cropSeasonId: x.crop_season_id,
  activityType: x.activity_type,
  occurredAt: x.occurred_at,
  note: x.note ?? null,
  data: x.data,
  createdBy: x.created_by,
  createdAt: x.created_at,
  updatedAt: x.updated_at,
  idempotentReplay: Boolean(x.idempotent_replay),
})

export interface CreateActivityParams {
  occurredAt: string
  note?: string | null
  idempotencyKey: string
}

export async function createActivity(cropSeasonId: string, input: ActivityInput, params: CreateActivityParams): Promise<ActivityWriteResult> {
  const body = {
    idempotency_key: params.idempotencyKey,
    activity_type: input.activityType,
    occurred_at: params.occurredAt,
    note: params.note ?? null,
    data: activityDataPayload(input),
  }
  return mapWriteResult(await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/activities`, { method: 'POST', body: JSON.stringify(body) }))
}

export interface UpdateActivityParams {
  occurredAt: string
  note?: string | null
}

export async function updateActivity(activityId: string, input: ActivityInput, params: UpdateActivityParams): Promise<ActivityWriteResult> {
  const body = {
    occurred_at: params.occurredAt,
    note: params.note ?? null,
    data: activityDataPayload(input),
  }
  return mapWriteResult(await apiRequest<any>(`/v1/activities/${activityId}`, { method: 'PATCH', body: JSON.stringify(body) }))
}

export async function deleteActivity(activityId: string): Promise<void> {
  await apiRequest<void>(`/v1/activities/${activityId}`, { method: 'DELETE' })
}
