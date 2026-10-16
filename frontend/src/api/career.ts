import { apiJson } from './client'
import type {
  RunnerStatus,
  RunCareerBody,
  DeleteCareerBody,
  BurnClocksBody,
  SyncSelectionBody,
  GetFriendsBody,
  DeleteParentsBody,
  AutoDeleteConfig,
  Account,
  FriendInfo,
  ParentInfo,
  Selection,
  EventInfo,
  RentalQuota,
} from './types'

/** POST /api/career/run — start or resume a career run */
export const runCareer = (body: RunCareerBody, account?: string) =>
  apiJson<{ success: boolean; runner?: RunnerStatus; account?: Account; detail?: string }>(
    '/api/career/run',
    { method: 'POST', body, account },
  )

/** GET /api/career/runner — poll current runner state */
export const getRunner = (account?: string) =>
  apiJson<{ success: boolean; runner?: RunnerStatus }>('/api/career/runner', { account })

/** POST /api/career/runner/pause */
export const pauseRunner = (account?: string) =>
  apiJson<{ success: boolean; runner?: RunnerStatus }>('/api/career/runner/pause', {
    method: 'POST',
    account,
  })

/** POST /api/career/runner/resume */
export const resumeRunner = (account?: string) =>
  apiJson<{ success: boolean; runner?: RunnerStatus }>('/api/career/runner/resume', {
    method: 'POST',
    account,
  })

/** PATCH /api/career/runner — toggle burn-clocks on a live runner */
export const setBurnClocks = (body: BurnClocksBody) =>
  apiJson<{ success: boolean; runner?: RunnerStatus; detail?: string }>(
    '/api/career/runner',
    { method: 'PATCH', body },
  )

/** POST /api/career/delete — force-delete the ongoing career */
export const deleteCareer = (body: DeleteCareerBody) =>
  apiJson<{ success: boolean; account?: Account; detail?: string }>('/api/career/delete', {
    method: 'POST',
    body,
  })

/** GET /api/career/friends — load/refresh friend list */
export const getFriends = (body: GetFriendsBody) => {
  const params = new URLSearchParams()
  body.exclude_viewer_ids.forEach(id => params.append('exclude_viewer_ids', String(id)))
  const qs = params.toString()
  const url = qs ? `/api/career/friends?${qs}` : '/api/career/friends'
  return apiJson<{
    success: boolean
    friends?: FriendInfo[]
    rental_quota?: RentalQuota
    exclude_viewer_ids?: (number | string)[]
    source?: string
    detail?: string
  }>(url, { method: 'GET' })
}

/** DELETE /api/parents — delete one or many of my trained characters (ids + unlock flag in the body) */
export const deleteParents = (body: DeleteParentsBody, account?: string) =>
  apiJson<{
    success: boolean
    deleted?: (number | string)[]
    parents?: ParentInfo[]
    locked?: (number | string)[]
    detail?: string
  }>('/api/parents', { method: 'DELETE', body, account })

/** POST /api/parents/refresh - rebuild my veteran roster from live game state */
export const refreshParents = (account?: string) =>
  apiJson<{
    success: boolean
    parents?: ParentInfo[]
    selection?: Selection
    removed_veteran_ids?: (number | string | null)[]
    detail?: string
  }>('/api/parents/refresh', { method: 'POST', account })

/** GET /api/parents/auto-delete-config — load just-trained auto-delete config */
export const getAutoDeleteConfig = (account?: string) =>
  apiJson<{ success: boolean; config: AutoDeleteConfig; detail?: string }>(
    '/api/parents/auto-delete-config',
    { account },
  )

/** POST /api/parents/auto-delete-config — save just-trained auto-delete config */
export const setAutoDeleteConfig = (body: AutoDeleteConfig, account?: string) =>
  apiJson<{ success: boolean; config: AutoDeleteConfig; detail?: string }>(
    '/api/parents/auto-delete-config',
    { method: 'POST', body, account },
  )

/** GET /api/career/event-info — active story/event difficulty info */
export const getEventInfo = () => apiJson<EventInfo>('/api/career/event-info')

/** POST /api/selection — sync current selection to server */
export const syncSelection = (body: SyncSelectionBody) =>
  apiJson<{ success: boolean; [k: string]: unknown }>('/api/selection', {
    method: 'POST',
    body,
  })
