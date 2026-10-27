import { ApiError } from '../services/api'
import type { Target, TargetCapability, TargetState } from '../services/types'

export type TargetStatus = TargetState

export function classifyTargetStatus(enabled: boolean, hasActiveReservation: boolean): TargetStatus {
  if (!enabled) return 'disabled'
  if (hasActiveReservation) return 'reserved'
  return 'available'
}

export function targetState(target: Target): TargetState {
  if (target.availability?.state) return target.availability.state
  if (!target.enabled) return 'disabled'
  return target.status === 'available' ? 'available' : target.status
}

export function prettyDate(value?: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

export function prettyTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** "in 12 min", "3 h ago" */
export function relativeTime(value?: string | null, now: number = Date.now()): string {
  if (!value) return '-'
  const diff = new Date(value).getTime() - now
  const minutes = Math.round(Math.abs(diff) / 60_000)
  const text = minutes < 1 ? 'less than a minute' : minutes < 90 ? `${minutes} min` : `${Math.round(minutes / 60)} h`
  return diff >= 0 ? `in ${text}` : `${text} ago`
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind() === 'unauthorized') return 'Your session expired. Please sign in again.'
    if (error.kind() === 'forbidden') return error.message && error.message !== 'forbidden'
      ? error.message
      : 'You do not have permission for this action.'
    if (error.kind() === 'conflict') return error.message || 'The request conflicts with the current state.'
    if (error.kind() === 'offline') return 'TargetHub server is unreachable. Check your network connection.'
    if (error.kind() === 'validation') return `Validation failed: ${error.message}`
    if (error.kind() === 'rate_limited') return 'Too many attempts. Please wait a few minutes and try again.'
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Unexpected error'
}

// datetime-local inputs expect local wall-clock time, not UTC.
export function toLocalInputValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

const MODE_LABELS: Record<string, string> = {
  agent: 'via Agent',
  dd: 'DD power',
  http: 'HTTP controller',
  simulated: 'simulated',
  serial: 'server port',
  unconfigured: 'not configured',
  invalid: 'invalid config',
}

export function capabilityModeLabel(capability: Pick<TargetCapability, 'mode' | 'hosting'>): string {
  return MODE_LABELS[capability.mode] || capability.mode || capability.hosting
}

export function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
