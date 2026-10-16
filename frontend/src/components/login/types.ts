/** Shared status line state for login sub-panels */
export type StatusKind = 'idle' | 'working' | 'ok' | 'error'

export interface StatusState {
  kind: StatusKind
  message: string
}
