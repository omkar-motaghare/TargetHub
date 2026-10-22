import { describe, expect, it } from 'vitest'

import { ApiError, formatApiErrorDetail } from '../services/api'
import { classifyTargetStatus, errorMessage, toLocalInputValue } from './ui'

describe('classifyTargetStatus', () => {
  it('returns disabled when target is disabled', () => {
    expect(classifyTargetStatus(false, false)).toBe('disabled')
  })

  it('returns reserved when enabled target has active reservation', () => {
    expect(classifyTargetStatus(true, true)).toBe('reserved')
  })

  it('returns available for enabled target without reservation', () => {
    expect(classifyTargetStatus(true, false)).toBe('available')
  })
})

describe('errorMessage', () => {
  it('maps unauthorized api errors to session-expired message', () => {
    const err = new ApiError(401, 'token expired')
    expect(errorMessage(err)).toContain('session expired')
  })

  it('maps conflict api errors to conflict-prefixed message', () => {
    const err = new ApiError(409, 'reservation conflict')
    expect(errorMessage(err)).toContain('Conflict: reservation conflict')
  })

  it('returns generic Error messages as-is', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
  })

  it('formats FastAPI validation details without object coercion', () => {
    const detail = [
      { loc: ['body', 'username'], msg: 'Field required', type: 'missing' },
      { loc: ['body', 'password'], msg: 'Field required', type: 'missing' },
    ]

    expect(formatApiErrorDetail(detail)).toBe('username: Field required; password: Field required')
  })
})

describe('toLocalInputValue', () => {
  it('formats the local wall-clock time for datetime-local inputs', () => {
    const date = new Date(2030, 0, 2, 3, 4)
    expect(toLocalInputValue(date)).toBe('2030-01-02T03:04')
  })
})
