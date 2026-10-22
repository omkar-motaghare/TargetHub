import { ApiError } from '../services/api'

export type TargetStatus = 'available' | 'reserved' | 'disabled'

export function classifyTargetStatus(enabled: boolean, hasActiveReservation: boolean): TargetStatus {
  if (!enabled) return 'disabled'
  if (hasActiveReservation) return 'reserved'
  return 'available'
}

export function prettyDate(value?: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind() === 'unauthorized') return 'Your session expired. Please sign in again.'
    if (error.kind() === 'forbidden') return 'You are authenticated but do not have permission for this action.'
    if (error.kind() === 'conflict') return `Conflict: ${error.message}`
    if (error.kind() === 'offline') return 'TargetHub API is unreachable. Check backend connectivity.'
    if (error.kind() === 'validation') return `Validation failed: ${error.message}`
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Unexpected error'
}