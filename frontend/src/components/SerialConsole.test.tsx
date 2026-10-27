import React from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const written: string[] = []
let dataHandler: ((data: string) => void) | null = null

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    loadAddon() {}
    open() {}
    write(text: string) { written.push(text) }
    onData(handler: (data: string) => void) { dataHandler = handler }
    focus() {}
    clear() {}
    dispose() {}
  },
}))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))
vi.mock('@xterm/xterm/css/xterm.css', () => ({}))
vi.mock('../services/api', () => ({
  getAuthToken: () => 'access-1',
  refreshAccessToken: vi.fn().mockResolvedValue(true),
  serialLog: vi.fn().mockResolvedValue('log'),
  serialSocketUrl: (id: string) => `ws://hub/api/v1/sessions/${id}/serial/ws`,
}))

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 1
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    FakeSocket.instances.push(this)
  }
  send(data: string) { this.sent.push(data) }
  close() { this.readyState = 3 }
  receive(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) }) }
}

import SerialConsole from './SerialConsole'

describe('SerialConsole', () => {
  beforeEach(() => {
    written.length = 0
    FakeSocket.instances = []
    vi.stubGlobal('WebSocket', FakeSocket)
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('authenticates with the first frame, renders output and forwards keystrokes', () => {
    const onEnded = vi.fn()
    render(<SerialConsole sessionId="s1" onEnded={onEnded} />)
    const socket = FakeSocket.instances[0]
    expect(socket.url).toBe('ws://hub/api/v1/sessions/s1/serial/ws')

    act(() => socket.onopen?.())
    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'auth', token: 'access-1' })

    act(() => socket.receive({ type: 'ready', session_id: 's1' }))
    expect(screen.getByText('Connected')).toBeInTheDocument()

    act(() => socket.receive({ type: 'output', data: 'U-Boot 2026\r\n' }))
    expect(written.join('')).toContain('U-Boot 2026')

    act(() => dataHandler?.('ls\r'))
    expect(JSON.parse(socket.sent[1])).toEqual({ type: 'input', data: 'ls\r' })

    act(() => socket.receive({ type: 'closed', reason: 'Session is closed' }))
    expect(screen.getByText('Session ended')).toBeInTheDocument()
    expect(onEnded).toHaveBeenCalledWith('Session is closed')
  })

  it('reconnects after an unexpected disconnect', () => {
    vi.useFakeTimers()
    render(<SerialConsole sessionId="s1" />)
    const first = FakeSocket.instances[0]
    act(() => first.onclose?.())
    expect(screen.getByText('Reconnecting…')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1100))
    expect(FakeSocket.instances).toHaveLength(2)
    vi.useRealTimers()
  })
})
