import { apiJson } from './client'
import type {
  EventCatalogResponse,
  EventPrefsResponse,
  RebuildCatalogResponse,
  SaveEventPrefsBody,
  UpdateEventDatabaseResponse,
} from './types'

/** GET /api/events/catalog — list all captured events */
export const getEventCatalog = () =>
  apiJson<EventCatalogResponse>('/api/events/catalog')

/** POST /api/events/catalog/rebuild — re-parse logs; slow (~8 s) */
export const rebuildEventCatalog = () =>
  apiJson<RebuildCatalogResponse>('/api/events/catalog/rebuild', { method: 'POST' })

/** GET /api/events/prefs — load per-story_id choice preferences */
export const getEventPrefs = () =>
  apiJson<EventPrefsResponse>('/api/events/prefs')

/** POST /api/events/prefs — save per-story_id choice preferences */
export const saveEventPrefs = (prefs: Record<string, number>) =>
  apiJson<{ success: boolean }>('/api/events/prefs', {
    method: 'POST',
    body: { prefs } satisfies SaveEventPrefsBody,
  })

/**
 * POST /api/events/catalog/refresh — re-scrapes gametora and rebuilds the
 * catalog.  Network operation; may take ~10 s.
 */
export const updateEventDatabase = () =>
  apiJson<UpdateEventDatabaseResponse>('/api/events/catalog/refresh', {
    method: 'POST',
  })
