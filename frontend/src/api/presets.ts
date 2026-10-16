import { apiJson } from './client'
import type {
  Preset,
  RacePreset,
  SkillEntry,
  SavePresetBody,
  DeletePresetBody,
  GetRacePresetsResponse,
  SaveRacePresetBody,
  DeleteRacePresetBody,
  SaveRacesToRacePresetBody,
} from './types'

/** GET /api/presets — list all presets */
export const getPresets = () =>
  apiJson<{ success: boolean; presets?: Preset[] }>('/api/presets')

/** POST /api/presets — create or update a preset */
export const savePreset = (body: SavePresetBody) =>
  apiJson<{ success: boolean; preset?: Preset; detail?: string }>('/api/presets', {
    method: 'POST',
    body,
  })

/** DELETE /api/presets/{name} — delete a preset by name */
export const deletePreset = (body: DeletePresetBody) =>
  apiJson<{ success: boolean; detail?: string }>(`/api/presets/${encodeURIComponent(body.name)}`, {
    method: 'DELETE',
  })

/** GET /api/skills — load skill catalogue */
export const getSkills = () =>
  apiJson<{ success: boolean; skills?: SkillEntry[] }>('/api/skills')

// ---------------------------------------------------------------------------
// Race preset API
// ---------------------------------------------------------------------------

/** GET /api/presets?kind=race — list all race presets */
export const getRacePresets = () =>
  apiJson<GetRacePresetsResponse>('/api/presets?kind=race')

/** POST /api/presets?kind=race — create or update a race preset */
export const saveRacePreset = (body: SaveRacePresetBody) =>
  apiJson<{ success: boolean; preset?: RacePreset; detail?: string }>('/api/presets?kind=race', {
    method: 'POST',
    body,
  })

/** DELETE /api/presets/{name}?kind=race — delete a race preset by name */
export const deleteRacePreset = (body: DeleteRacePresetBody) =>
  apiJson<{ success: boolean; detail?: string }>(`/api/presets/${encodeURIComponent(body.name)}?kind=race`, {
    method: 'DELETE',
  })

/** PUT /api/presets/{name}/races?kind=race — upsert race list for a race preset */
export const saveRacesToRacePreset = (body: SaveRacesToRacePresetBody) =>
  apiJson<{ success: boolean; detail?: string }>(`/api/presets/${encodeURIComponent(body.preset_name)}/races?kind=race`, {
    method: 'PUT',
    body: { races: body.races },
  })
