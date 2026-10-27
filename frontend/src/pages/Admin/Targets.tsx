import React, { useEffect, useMemo, useState } from 'react'

import StateBadge from '../../components/StateBadge'
import {
  checkPower,
  getSystemOverview,
  createCapability,
  createTarget,
  deleteCapability,
  deleteTarget,
  forceReleaseReservation,
  listAgents,
  listReservations,
  listTargets,
  updateCapability,
  updateTarget,
} from '../../services/api'
import type {
  Agent,
  CapabilityType,
  Reservation,
  Target,
  TargetCapability,
  TargetCapabilityCreateInput,
  SystemIssue,
} from '../../services/types'
import { capabilityModeLabel, errorMessage, prettyTime, targetState } from '../../utils/ui'

/** Where a capability executes. */
type Backend = 'agent' | 'dd' | 'http' | 'simulated' | 'custom'

type EditableCapability = {
  id?: string
  name: string
  capability_type: CapabilityType
  enabled: boolean
  backend: Backend
  agent_id: string | null
  resource_id: string | null
  provider_key: string
  /** Every provider_config key, including ones this form does not edit. */
  config: Record<string, unknown>
  /** Raw JSON for the "custom" backend. */
  json: string
}

type TargetForm = {
  id?: string
  name: string
  description: string
  vendor: string
  board_model: string
  serial_number: string
  lab_name: string
  location: string
  tags: string
  status: Target['status']
  status_reason: string
  enabled: boolean
  capabilities: EditableCapability[]
}

const CAPABILITY_TYPES: { value: CapabilityType; label: string }[] = [
  { value: 'serial', label: 'Serial console' },
  { value: 'power', label: 'Power' },
  { value: 'reset', label: 'Reset' },
  { value: 'deploy', label: 'Firmware deploy' },
  { value: 'jlink', label: 'Debugger (J-Link bridge)' },
  { value: 'network', label: 'Network bridge' },
  { value: 'ssh', label: 'SSH bridge' },
  { value: 'telnet', label: 'Telnet bridge' },
  { value: 'ftp', label: 'FTP bridge' },
]

const BACKENDS: Record<CapabilityType, Backend[]> = {
  serial: ['agent', 'simulated'],
  power: ['agent', 'dd', 'http', 'simulated'],
  reset: ['agent', 'dd', 'http', 'simulated'],
  deploy: ['agent', 'custom', 'simulated'],
  jlink: ['custom', 'simulated'],
  network: ['custom', 'simulated'],
  ssh: ['custom', 'simulated'],
  telnet: ['custom', 'simulated'],
  ftp: ['custom', 'simulated'],
}

const BACKEND_LABELS: Record<Backend, string> = {
  agent: 'Agent hardware',
  dd: 'DD power system (server)',
  http: 'HTTP power controller (server)',
  simulated: 'Simulated (demo only)',
  custom: 'HTTP bridge (server, JSON config)',
}

const RESOURCE_TYPES: Record<string, string[]> = {
  serial: ['serial'],
  power: ['power'],
  reset: ['power', 'reset'],
  deploy: ['deploy'],
}

function inferBackend(capability: TargetCapability): Backend {
  const config = capability.provider_config || {}
  if (capability.agent_id && capability.resource_id) return 'agent'
  if (config.driver === 'dd') return 'dd'
  if (config.driver === 'http' || config.mode === 'real') {
    return capability.capability_type === 'power' || capability.capability_type === 'reset' ? 'http' : 'custom'
  }
  if (config.driver === 'simulated' || config.mode === 'simulated' || Object.keys(config).length === 0) return 'simulated'
  return 'custom'
}

function newCapability(type: CapabilityType = 'serial'): EditableCapability {
  return {
    name: type === 'serial' ? 'Console' : type === 'power' ? 'Power' : '',
    capability_type: type,
    enabled: true,
    backend: BACKENDS[type][0],
    agent_id: null,
    resource_id: null,
    provider_key: '',
    config: type === 'power' ? { cycle_delay_seconds: 3, confirm_timeout_seconds: 10 } : {},
    json: '{}',
  }
}

function toEditable(capability: TargetCapability): EditableCapability {
  const config = { ...(capability.provider_config || {}) }
  return {
    id: capability.id,
    name: capability.name,
    capability_type: capability.capability_type,
    enabled: capability.enabled,
    backend: inferBackend(capability),
    agent_id: capability.agent_id || null,
    resource_id: capability.resource_id || null,
    provider_key: capability.provider_key || '',
    config,
    json: JSON.stringify(config, null, 2),
  }
}

function blankForm(): TargetForm {
  return {
    name: '', description: '', vendor: '', board_model: '', serial_number: '', lab_name: '', location: '',
    tags: '', status: 'available', status_reason: '', enabled: true, capabilities: [],
  }
}

export function capabilityPayload(row: EditableCapability): TargetCapabilityCreateInput {
  const base = {
    name: row.name.trim(),
    capability_type: row.capability_type,
    enabled: row.enabled,
    provider_key: row.provider_key.trim() || null,
  }
  if (row.backend === 'agent') {
    const { driver: _driver, mode: _mode, ...rest } = row.config
    return { ...base, agent_id: row.agent_id, resource_id: row.resource_id, provider_config: rest }
  }
  if (row.backend === 'custom') {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(row.json || '{}')
    } catch {
      throw new Error(`Capability "${row.name}": provider configuration is not valid JSON`)
    }
    return { ...base, agent_id: null, resource_id: null, provider_config: parsed }
  }
  if (row.backend === 'simulated') {
    return { ...base, agent_id: null, resource_id: null, provider_config: { ...row.config, driver: 'simulated', mode: 'simulated' } }
  }
  const { mode: _mode, ...rest } = row.config
  const config: Record<string, unknown> = { ...rest, driver: row.backend }
  for (const key of ['node_id', 'endpoint', 'cycle_delay_seconds', 'confirm_timeout_seconds', 'timeout_seconds']) {
    if (config[key] === '' || config[key] === undefined) delete config[key]
    else if (typeof config[key] === 'string') config[key] = Number(config[key])
  }
  if (!config.api_key_env) delete config.api_key_env
  return { ...base, agent_id: null, resource_id: null, provider_config: config }
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={wide ? 'wide' : undefined}>
      <span className="muted">{label}</span>
      {children}
    </label>
  )
}

function CapabilityEditor({
  row,
  agents,
  onChange,
  onRemove,
}: {
  row: EditableCapability
  agents: Agent[]
  onChange: (patch: Partial<EditableCapability>) => void
  onRemove: () => void
}) {
  const agent = agents.find((item) => item.id === row.agent_id)
  const wanted = RESOURCE_TYPES[row.capability_type] || []
  const resources = (agent?.resources || []).filter(
    (resource) => resource.available && (!wanted.length || wanted.includes(resource.resource_type)),
  )
  const setConfig = (key: string, value: unknown) => onChange({ config: { ...row.config, [key]: value } })
  const text = (key: string) => String(row.config[key] ?? '')
  const [check, setCheck] = useState<{ busy: boolean; ok?: boolean; text?: string }>({ busy: false })
  const canCheck = row.backend === 'dd' || row.backend === 'http'

  async function testConnection(): Promise<void> {
    setCheck({ busy: true })
    try {
      const payload = capabilityPayload(row)
      const result = await checkPower(row.capability_type, payload.provider_config || {})
      const state = result.data && typeof result.data.state === 'string' ? ` · state: ${result.data.state}` : ''
      setCheck({ busy: false, ok: result.success, text: `${result.message}${state}` })
    } catch (error) {
      setCheck({ busy: false, ok: false, text: errorMessage(error) })
    }
  }

  return (
    <div className="capability-row">
      <Field label="Name">
        <input className="input" value={row.name} placeholder="Console" onChange={(e) => onChange({ name: e.target.value })} />
      </Field>
      <Field label="Type">
        <select className="select" value={row.capability_type}
          onChange={(e) => {
            const type = e.target.value as CapabilityType
            onChange({ capability_type: type, backend: BACKENDS[type][0], agent_id: null, resource_id: null })
          }}>
          {CAPABILITY_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </Field>
      <Field label="Runs on">
        <select className="select" value={row.backend} onChange={(e) => onChange({ backend: e.target.value as Backend })}>
          {BACKENDS[row.capability_type].map((backend) => <option key={backend} value={backend}>{BACKEND_LABELS[backend]}</option>)}
        </select>
      </Field>
      <Field label="Enabled">
        <select className="select" value={row.enabled ? 'yes' : 'no'} onChange={(e) => onChange({ enabled: e.target.value === 'yes' })}>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      </Field>

      {row.backend === 'agent' && (
        <>
          <Field label="Agent">
            <select className="select" value={row.agent_id || ''} onChange={(e) => onChange({ agent_id: e.target.value || null, resource_id: null })}>
              <option value="">Select an Agent…</option>
              {agents.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.status})</option>)}
            </select>
          </Field>
          <Field label="Hardware resource" wide>
            <select className="select" value={row.resource_id || ''} onChange={(e) => onChange({ resource_id: e.target.value || null })}>
              <option value="">{agent ? (resources.length ? 'Select a discovered resource…' : 'No matching resources reported by this Agent') : 'Select an Agent first'}</option>
              {resources.map((resource) => (
                <option key={resource.id} value={resource.id}>
                  {resource.display_name} ({resource.resource_type}){resource.metadata?.simulated ? ' · simulated' : ''}
                </option>
              ))}
            </select>
          </Field>
        </>
      )}

      {row.backend === 'dd' && (
        <>
          <Field label="DD server URL" wide>
            <input className="input" placeholder="http://dd-server:5003" value={text('base_url')} onChange={(e) => setConfig('base_url', e.target.value)} />
          </Field>
          <Field label="Hub MAC">
            <input className="input mono" placeholder="AA:BB:CC:DD:EE:FF" value={text('hub_mac')} onChange={(e) => setConfig('hub_mac', e.target.value)} />
          </Field>
          <Field label="Node ID">
            <input className="input" type="number" min={0} value={text('node_id')} onChange={(e) => setConfig('node_id', e.target.value)} />
          </Field>
          <Field label="Endpoint">
            <input className="input" type="number" min={0} value={text('endpoint')} onChange={(e) => setConfig('endpoint', e.target.value)} />
          </Field>
          <Field label="API key env var (on the server)">
            <input className="input mono" placeholder="TARGETHUB_DD_API_KEY" value={text('api_key_env')} onChange={(e) => setConfig('api_key_env', e.target.value)} />
          </Field>
          <Field label="Cycle off-time (s)">
            <input className="input" type="number" min={0.5} step={0.5} value={text('cycle_delay_seconds')} onChange={(e) => setConfig('cycle_delay_seconds', e.target.value)} />
          </Field>
          <Field label="Confirm timeout (s)">
            <input className="input" type="number" min={0} value={text('confirm_timeout_seconds')} onChange={(e) => setConfig('confirm_timeout_seconds', e.target.value)} />
          </Field>
        </>
      )}

      {row.backend === 'http' && (
        <>
          <Field label="Controller URL" wide>
            <input className="input" placeholder="https://pdu.lab.local" value={text('controller_url')} onChange={(e) => setConfig('controller_url', e.target.value)} />
          </Field>
          <Field label="Outlet ID">
            <input className="input" value={text('outlet_id')} onChange={(e) => setConfig('outlet_id', e.target.value)} />
          </Field>
          <Field label="Auth">
            <select className="select" value={text('auth_type') || 'none'} onChange={(e) => setConfig('auth_type', e.target.value)}>
              <option value="none">None</option>
              <option value="bearer">Bearer token (env var)</option>
              <option value="basic">Basic auth (env vars)</option>
            </select>
          </Field>
          {row.config.auth_type === 'bearer' && (
            <Field label="Token env var">
              <input className="input mono" value={text('bearer_token_env')} onChange={(e) => setConfig('bearer_token_env', e.target.value)} />
            </Field>
          )}
          {row.config.auth_type === 'basic' && (
            <>
              <Field label="Username env var">
                <input className="input mono" value={text('basic_username_env')} onChange={(e) => setConfig('basic_username_env', e.target.value)} />
              </Field>
              <Field label="Password env var">
                <input className="input mono" value={text('basic_password_env')} onChange={(e) => setConfig('basic_password_env', e.target.value)} />
              </Field>
            </>
          )}
        </>
      )}

      {row.backend === 'custom' && (
        <Field label='Provider configuration (JSON, e.g. {"mode": "real", "controller_url": "…"})' wide>
          <textarea className="textarea mono" rows={4} value={row.json} onChange={(e) => onChange({ json: e.target.value })} />
        </Field>
      )}

      {row.backend === 'simulated' && (
        <div className="wide inline-note warn">
          Simulated capabilities control no hardware. The server refuses them unless ALLOW_SIMULATED_PROVIDERS=true.
        </div>
      )}

      <div className="wide capability-actions">
        {canCheck && (
          <button className="button secondary" type="button" onClick={() => void testConnection()} disabled={check.busy}
            title="Read the power status from the server with this configuration (does not switch anything)">
            {check.busy ? 'Testing…' : 'Test connection'}
          </button>
        )}
        <button className="button danger" type="button" onClick={onRemove}>Remove</button>
      </div>
      {check.text && (
        <div className={`wide inline-note ${check.ok ? 'ok' : 'warn'}`} role="status">
          {check.ok ? 'Connected: ' : 'Not working: '}{check.text}
        </div>
      )}
    </div>
  )
}

export default function AdminTargets() {
  const [targets, setTargets] = useState<Target[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [issues, setIssues] = useState<SystemIssue[]>([])
  const [form, setForm] = useState<TargetForm>(blankForm)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)

  async function refresh(): Promise<void> {
    setLoading(true)
    try {
      const [targetRows, reservationRows, agentRows] = await Promise.all([
        listTargets(),
        listReservations({ status: 'active' }),
        listAgents(),
      ])
      setTargets(targetRows)
      setReservations(reservationRows)
      setAgents(agentRows)
      // The configuration check is advisory; the page works without it.
      getSystemOverview().then((overview) => setIssues(overview.issues)).catch(() => setIssues([]))
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const agentsById = useMemo(() => Object.fromEntries(agents.map((agent) => [agent.id, agent])), [agents])

  function edit(target: Target): void {
    setForm({
      id: target.id,
      name: target.name,
      description: target.description || '',
      vendor: target.vendor || '',
      board_model: target.board_model || '',
      serial_number: target.serial_number || '',
      lab_name: target.lab_name || '',
      location: target.location || '',
      tags: (target.tags || []).join(', '),
      status: target.status,
      status_reason: target.status_reason || '',
      enabled: target.enabled,
      capabilities: (target.capabilities || []).map(toEditable),
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const setField = <K extends keyof TargetForm>(key: K, value: TargetForm[K]) => setForm((current) => ({ ...current, [key]: value }))

  function patchCapability(index: number, patch: Partial<EditableCapability>): void {
    setForm((current) => {
      const rows = [...current.capabilities]
      rows[index] = { ...rows[index], ...patch }
      return { ...current, capabilities: rows }
    })
  }

  async function save(): Promise<void> {
    if (!form.name.trim()) {
      setMessage({ kind: 'error', text: 'Target name is required.' })
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const rows = form.capabilities.filter((row) => row.name.trim())
      const payloads = rows.map((row) => ({ row, payload: capabilityPayload(row) }))
      const missingResource = payloads.find(({ row }) => row.backend === 'agent' && (!row.agent_id || !row.resource_id))
      if (missingResource) throw new Error(`Capability "${missingResource.row.name}": select an Agent and a hardware resource`)
      const targetPayload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        vendor: form.vendor.trim() || null,
        board_model: form.board_model.trim() || null,
        serial_number: form.serial_number.trim() || null,
        lab_name: form.lab_name.trim() || null,
        location: form.location.trim() || null,
        tags: form.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
        status: form.status,
        status_reason: form.status === 'available' ? null : form.status_reason.trim() || null,
        enabled: form.enabled,
      }
      if (!form.id) {
        await createTarget({ ...targetPayload, capabilities: payloads.map(({ payload }) => payload) })
      } else {
        const current = targets.find((target) => target.id === form.id)
        if (!current) throw new Error('Target no longer exists')
        await updateTarget(form.id, targetPayload)
        const keep = new Set(rows.filter((row) => row.id).map((row) => row.id))
        for (const old of current.capabilities || []) {
          if (!keep.has(old.id)) await deleteCapability(form.id, old.id)
        }
        for (const { row, payload } of payloads) {
          if (row.id) await updateCapability(form.id, row.id, payload)
          else await createCapability(form.id, payload)
        }
      }
      setMessage({ kind: 'info', text: `${targetPayload.name} saved.` })
      setForm(blankForm())
      await refresh()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function remove(target: Target): Promise<void> {
    if (!window.confirm(`Delete ${target.name}, its capabilities and reservation history?`)) return
    setBusy(true)
    try {
      await deleteTarget(target.id)
      if (form.id === target.id) setForm(blankForm())
      await refresh()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function forceRelease(reservation: Reservation, target: Target): Promise<void> {
    if (!window.confirm(`Force-release ${target.name} from ${reservation.user_id}? Their sessions close immediately.`)) return
    setBusy(true)
    try {
      await forceReleaseReservation(reservation.id)
      await refresh()
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div>}

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>{form.id ? `Edit ${form.name || 'target'}` : 'Add a target'}</h3>
          <div className="toolbar">
            {form.id && <button className="button ghost" onClick={() => setForm(blankForm())} disabled={busy} type="button">Cancel</button>}
            <button className="button" onClick={() => void save()} disabled={busy} type="button">{busy ? 'Saving…' : 'Save target'}</button>
          </div>
        </div>

        <div className="grid three" style={{ marginBottom: '0.8rem' }}>
          <Field label="Name *"><input className="input" value={form.name} onChange={(e) => setField('name', e.target.value)} placeholder="BOARD-01" /></Field>
          <Field label="Vendor"><input className="input" value={form.vendor} onChange={(e) => setField('vendor', e.target.value)} /></Field>
          <Field label="Board model"><input className="input" value={form.board_model} onChange={(e) => setField('board_model', e.target.value)} /></Field>
          <Field label="Serial number"><input className="input" value={form.serial_number} onChange={(e) => setField('serial_number', e.target.value)} /></Field>
          <Field label="Lab"><input className="input" value={form.lab_name} onChange={(e) => setField('lab_name', e.target.value)} /></Field>
          <Field label="Location"><input className="input" value={form.location} onChange={(e) => setField('location', e.target.value)} placeholder="Rack 2, shelf 3" /></Field>
          <Field label="Tags (comma separated)"><input className="input" value={form.tags} onChange={(e) => setField('tags', e.target.value)} placeholder="stm32-nucleo, lab-a" /></Field>
          <Field label="Status">
            <select className="select" value={form.status} onChange={(e) => setField('status', e.target.value as Target['status'])}>
              <option value="available">Available</option>
              <option value="maintenance">Maintenance (not reservable)</option>
              <option value="retired">Retired</option>
            </select>
          </Field>
          {form.status !== 'available' && (
            <Field label="Reason (shown to users)"><input className="input" value={form.status_reason} onChange={(e) => setField('status_reason', e.target.value)} placeholder="USB hub broken, replacement ordered" /></Field>
          )}
        </div>
        <Field label="Description">
          <textarea className="textarea" value={form.description} onChange={(e) => setField('description', e.target.value)} />
        </Field>

        <div style={{ marginTop: '0.9rem' }}>
          <div className="page-head">
            <h4 style={{ margin: 0 }}>Capabilities</h4>
            <div className="toolbar">
              <button className="button ghost" type="button" onClick={() => setForm((current) => ({ ...current, capabilities: [...current.capabilities, newCapability('serial')] }))}>+ Serial</button>
              <button className="button ghost" type="button" onClick={() => setForm((current) => ({ ...current, capabilities: [...current.capabilities, newCapability('power')] }))}>+ Power</button>
              <button className="button ghost" type="button" onClick={() => setForm((current) => ({ ...current, capabilities: [...current.capabilities, newCapability('deploy')] }))}>+ Deploy</button>
            </div>
          </div>
          {form.capabilities.length === 0 && (
            <p className="muted">No capabilities: users can still reserve the board (booking only). Add a serial console, power control or firmware deploy.</p>
          )}
          <div className="capability-grid">
            {form.capabilities.map((row, index) => (
              <CapabilityEditor key={row.id || index} row={row} agents={agents}
                onChange={(patch) => patchCapability(index, patch)}
                onRemove={() => setForm((current) => ({ ...current, capabilities: current.capabilities.filter((_, i) => i !== index) }))} />
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Targets ({targets.length})</h3>
          <button className="button" onClick={() => void refresh()} disabled={loading || busy}>{loading ? 'Loading…' : 'Refresh'}</button>
        </div>
        <div className="list">
          {!loading && targets.length === 0 && <div className="card empty">No targets yet.</div>}
          {targets.map((target) => {
            const reservation = reservations.find((item) => item.target_id === target.id && new Date(item.starts_at).getTime() <= Date.now())
            return (
              <article key={target.id} className="list-item stacked">
                <div className="row-between">
                  <div>
                    <div className="target-name">{target.name}</div>
                    {[target.vendor, target.board_model, target.lab_name, target.location].some(Boolean) && (
                      <div className="muted">{[target.vendor, target.board_model, target.lab_name, target.location].filter(Boolean).join(' · ')}</div>
                    )}
                  </div>
                  <StateBadge state={targetState(target)} />
                </div>
                <div className="chip-row">
                  {(target.tags || []).map((tag) => <span key={tag} className="chip tag">#{tag}</span>)}
                  {(target.capabilities || []).map((capability) => (
                    <span key={capability.id} className={`inline-note ${capability.mode === 'simulated' ? 'warn' : ''}`}>
                      {capability.name}: {capabilityModeLabel(capability)}
                      {capability.agent_id ? ` @ ${agentsById[capability.agent_id]?.name || 'unknown agent'}` : ''}
                      {!capability.enabled ? ' (disabled)' : ''}
                    </span>
                  ))}
                </div>
                {issues.filter((issue) => issue.target_id === target.id).map((issue, index) => (
                  <div key={index} className={`issue ${issue.severity}`}>
                    <span className={`issue-badge ${issue.severity}`}>{issue.severity === 'error' ? 'Error' : 'Warning'}</span>
                    {issue.message.replace(`${target.name} · `, '')}
                  </div>
                ))}
                <div className="row-between">
                  <div className="muted">
                    {reservation ? `Reserved by ${reservation.user_id} until ${prettyTime(reservation.ends_at)}` : target.status_reason || 'Not reserved'}
                  </div>
                  <div className="toolbar">
                    <button className="button ghost" onClick={() => edit(target)}>Edit</button>
                    {reservation && <button className="button secondary" onClick={() => void forceRelease(reservation, target)} disabled={busy}>Force release</button>}
                    <button className="button danger" onClick={() => void remove(target)} disabled={busy}>Delete</button>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}
