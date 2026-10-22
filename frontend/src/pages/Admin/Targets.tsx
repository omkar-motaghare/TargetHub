import React, { useEffect, useMemo, useState } from 'react'

import {
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
} from '../../services/types'
import { classifyTargetStatus, errorMessage, prettyDate } from '../../utils/ui'

type EditableCapability = {
  id?: string
  name: string
  capability_type: CapabilityType
  provider_key: string
  enabled: boolean
  agent_id: string | null
  resource_id: string | null
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
  enabled: boolean
  capabilities: EditableCapability[]
}

const CAPABILITY_TYPES: CapabilityType[] = [
  'serial',
  'network',
  'ssh',
  'telnet',
  'ftp',
  'jlink',
  'power',
  'reset',
  'deploy',
]

function newCapability(): EditableCapability {
  return {
    name: '',
    capability_type: 'serial',
    provider_key: 'serial-demo',
    enabled: true,
    agent_id: null,
    resource_id: null,
  }
}

function blankForm(): TargetForm {
  return {
    name: '',
    description: '',
    vendor: '',
    board_model: '',
    serial_number: '',
    lab_name: '',
    location: '',
    enabled: true,
    capabilities: [newCapability()],
  }
}

function toEditableCapability(capability: TargetCapability): EditableCapability {
  return {
    id: capability.id,
    name: capability.name,
    capability_type: capability.capability_type,
    provider_key: capability.provider_key || `${capability.capability_type}-demo`,
    enabled: capability.enabled,
    agent_id: capability.agent_id,
    resource_id: capability.resource_id,
  }
}

function capabilityPayload(capability: EditableCapability): TargetCapabilityCreateInput {
  return {
    name: capability.name.trim(),
    capability_type: capability.capability_type,
    provider_key: capability.provider_key.trim() || `${capability.capability_type}-demo`,
    enabled: capability.enabled,
    agent_id: capability.agent_id || null,
    resource_id: capability.resource_id || null,
    provider_config: {},
  }
}

export default function AdminTargets() {
  const [targets, setTargets] = useState<Target[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [form, setForm] = useState<TargetForm>(blankForm)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void refresh()
  }, [])

  async function refresh(): Promise<void> {
    setLoading(true)
    setMessage(null)
    try {
      const [targetRows, reservationRows, agentRows] = await Promise.all([
        listTargets(),
        listReservations(),
        listAgents(),
      ])
      setTargets(targetRows)
      setReservations(reservationRows)
      setAgents(agentRows)
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  const agentsById = useMemo(() => Object.fromEntries(agents.map((agent) => [agent.id, agent])), [agents])

  function editTarget(target: Target): void {
    setForm({
      id: target.id,
      name: target.name,
      description: target.description || '',
      vendor: target.vendor || '',
      board_model: target.board_model || '',
      serial_number: target.serial_number || '',
      lab_name: target.lab_name || '',
      location: target.location || '',
      enabled: target.enabled,
      capabilities: (target.capabilities || []).map(toEditableCapability),
    })
  }

  function resetForm(): void {
    setForm(blankForm())
  }

  function setField<K extends keyof TargetForm>(key: K, value: TargetForm[K]): void {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function updateCapabilityRow(index: number, patch: Partial<EditableCapability>): void {
    setForm((current) => {
      const rows = [...current.capabilities]
      rows[index] = { ...rows[index], ...patch }
      if (patch.capability_type && rows[index].provider_key.endsWith('-demo')) {
        rows[index].provider_key = `${patch.capability_type}-demo`
      }
      if (patch.agent_id !== undefined) {
        rows[index].resource_id = null
      }
      return { ...current, capabilities: rows }
    })
  }

  function addCapabilityRow(): void {
    setForm((current) => ({ ...current, capabilities: [...current.capabilities, newCapability()] }))
  }

  function removeCapabilityRow(index: number): void {
    setForm((current) => {
      const rows = [...current.capabilities]
      rows.splice(index, 1)
      return { ...current, capabilities: rows.length ? rows : [newCapability()] }
    })
  }

  function resourcesFor(agentId: string | null): { id: string; label: string }[] {
    if (!agentId) return []
    const agent = agentsById[agentId]
    if (!agent) return []
    return (agent.resources || [])
      .filter((resource) => resource.available)
      .map((resource) => ({ id: resource.id, label: `${resource.display_name} (${resource.resource_type})` }))
  }

  async function saveTarget(): Promise<void> {
    if (!form.name.trim()) {
      setMessage('Target name is required.')
      return
    }

    const cleanCapabilities = form.capabilities
      .map((capability) => ({ ...capability, name: capability.name.trim() }))
      .filter((capability) => capability.name.length > 0)

    if (!cleanCapabilities.length) {
      setMessage('At least one named capability is required.')
      return
    }

    setBusy(true)
    setMessage(null)
    try {
      const targetPayload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        vendor: form.vendor.trim() || null,
        board_model: form.board_model.trim() || null,
        serial_number: form.serial_number.trim() || null,
        lab_name: form.lab_name.trim() || null,
        location: form.location.trim() || null,
        enabled: form.enabled,
        status: 'available',
      }

      if (!form.id) {
        await createTarget({
          ...targetPayload,
          capabilities: cleanCapabilities.map((capability) => capabilityPayload(capability)),
        })
      } else {
        const current = targets.find((target) => target.id === form.id)
        if (!current) throw new Error('Target no longer exists')

        await updateTarget(form.id, targetPayload)

        const existingById = new Map((current.capabilities || []).map((capability) => [capability.id, capability]))
        const incomingIds = new Set(cleanCapabilities.filter((capability) => capability.id).map((capability) => capability.id!))

        for (const oldCapability of current.capabilities || []) {
          if (!incomingIds.has(oldCapability.id)) {
            await deleteCapability(form.id, oldCapability.id)
          }
        }

        for (const capability of cleanCapabilities) {
          const payload = capabilityPayload(capability)
          if (capability.id && existingById.has(capability.id)) {
            await updateCapability(form.id, capability.id, payload)
          } else {
            await createCapability(form.id, payload)
          }
        }
      }

      resetForm()
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function removeTarget(targetId: string): Promise<void> {
    if (!window.confirm('Delete this target and all capability mappings?')) return
    setBusy(true)
    setMessage(null)
    try {
      await deleteTarget(targetId)
      if (form.id === targetId) resetForm()
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function forceRelease(targetId: string): Promise<void> {
    const reservation = reservations.find((item) => item.target_id === targetId && item.status === 'active')
    if (!reservation) {
      setMessage('No active reservation exists for this target.')
      return
    }
    if (!window.confirm('Force-release this reservation? This also closes active sessions.')) return

    setBusy(true)
    setMessage(null)
    try {
      await forceReleaseReservation(reservation.id)
      await refresh()
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className="feedback error">{message}</div>}

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>{form.id ? 'Edit Target' : 'Create Target'}</h3>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {form.id && (
              <button className="button ghost" onClick={resetForm} disabled={busy} type="button">
                Cancel Edit
              </button>
            )}
            <button className="button" onClick={() => void saveTarget()} disabled={busy} type="button">
              {busy ? 'Saving...' : 'Save Target'}
            </button>
          </div>
        </div>

        <div className="grid two" style={{ marginBottom: '0.8rem' }}>
          <label>
            <span className="muted">Name</span>
            <input className="input" value={form.name} onChange={(event) => setField('name', event.target.value)} />
          </label>
          <label>
            <span className="muted">Vendor</span>
            <input className="input" value={form.vendor} onChange={(event) => setField('vendor', event.target.value)} />
          </label>
          <label>
            <span className="muted">Board model</span>
            <input
              className="input"
              value={form.board_model}
              onChange={(event) => setField('board_model', event.target.value)}
            />
          </label>
          <label>
            <span className="muted">Serial number</span>
            <input
              className="input"
              value={form.serial_number}
              onChange={(event) => setField('serial_number', event.target.value)}
            />
          </label>
          <label>
            <span className="muted">Lab</span>
            <input className="input" value={form.lab_name} onChange={(event) => setField('lab_name', event.target.value)} />
          </label>
          <label>
            <span className="muted">Location</span>
            <input className="input" value={form.location} onChange={(event) => setField('location', event.target.value)} />
          </label>
        </div>

        <label>
          <span className="muted">Description</span>
          <textarea
            className="textarea"
            value={form.description}
            onChange={(event) => setField('description', event.target.value)}
          />
        </label>

        <div style={{ marginTop: '0.9rem' }}>
          <div className="page-head">
            <h4 style={{ margin: 0 }}>Capabilities</h4>
            <button className="button ghost" type="button" onClick={addCapabilityRow}>
              Add capability
            </button>
          </div>

          <div className="capability-grid">
            {form.capabilities.map((capability, index) => {
              const resources = resourcesFor(capability.agent_id)
              return (
                <div key={capability.id || index} className="capability-row">
                  <label>
                    <span className="muted">Name</span>
                    <input
                      className="input"
                      value={capability.name}
                      placeholder="serial-console"
                      onChange={(event) => updateCapabilityRow(index, { name: event.target.value })}
                    />
                  </label>
                  <label>
                    <span className="muted">Type</span>
                    <select
                      className="select"
                      value={capability.capability_type}
                      onChange={(event) =>
                        updateCapabilityRow(index, { capability_type: event.target.value as CapabilityType })
                      }
                    >
                      {CAPABILITY_TYPES.map((type) => (
                        <option value={type} key={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="muted">Provider key</span>
                    <input
                      className="input"
                      value={capability.provider_key}
                      onChange={(event) => updateCapabilityRow(index, { provider_key: event.target.value })}
                    />
                  </label>
                  <label>
                    <span className="muted">Agent</span>
                    <select
                      className="select"
                      value={capability.agent_id || ''}
                      onChange={(event) => updateCapabilityRow(index, { agent_id: event.target.value || null })}
                    >
                      <option value="">Unassigned</option>
                      {agents.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name} ({agent.status})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide">
                    <span className="muted">Discovered resource</span>
                    <select
                      className="select"
                      value={capability.resource_id || ''}
                      onChange={(event) => updateCapabilityRow(index, { resource_id: event.target.value || null })}
                    >
                      <option value="">Unassigned</option>
                      {resources.map((resource) => (
                        <option key={resource.id} value={resource.id}>
                          {resource.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="muted">Enabled</span>
                    <select
                      className="select"
                      value={capability.enabled ? 'yes' : 'no'}
                      onChange={(event) => updateCapabilityRow(index, { enabled: event.target.value === 'yes' })}
                    >
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </label>
                  <div style={{ display: 'flex', alignItems: 'end' }}>
                    <button className="button danger" type="button" onClick={() => removeCapabilityRow(index)}>
                      Remove
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Managed Targets</h3>
          <button className="button" onClick={() => void refresh()} disabled={loading || busy}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        <div className="list">
          {!loading && targets.length === 0 && <div className="card">No targets found.</div>}
          {targets.map((target) => {
            const reservation = reservations.find(
              (item) => item.target_id === target.id && item.status === 'active',
            )
            const status = classifyTargetStatus(target.enabled, !!reservation)
            return (
              <article key={target.id} className="list-item stacked">
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.7rem' }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{target.name}</div>
                    <div className="muted">
                      {target.vendor || '-'} / {target.board_model || '-'} / {target.location || '-'}
                    </div>
                  </div>
                  <span className={`badge ${status}`}>{status}</span>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  {(target.capabilities || []).map((capability) => (
                    <span className="inline-note" key={capability.id}>
                      {capability.name} ({capability.capability_type})
                    </span>
                  ))}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.7rem', flexWrap: 'wrap' }}>
                  <div className="muted">
                    {reservation
                      ? `Reserved by ${reservation.user_id} until ${prettyDate(reservation.ends_at)}`
                      : 'No active reservation'}
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button className="button ghost" onClick={() => editTarget(target)}>
                      Edit
                    </button>
                    {reservation && (
                      <button className="button secondary" onClick={() => void forceRelease(target.id)} disabled={busy}>
                        Force release
                      </button>
                    )}
                    <button className="button danger" onClick={() => void removeTarget(target.id)} disabled={busy}>
                      Delete
                    </button>
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
