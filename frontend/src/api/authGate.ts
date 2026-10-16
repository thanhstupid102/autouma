import { apiJson } from './client'

export interface AuthGateStatus {
  gate_required: boolean
}

export const getAuthGateStatus = () =>
  apiJson<AuthGateStatus>('/api/auth-gate')
