import { describe, expect, it } from 'vitest'

import { capabilityPayload } from './Targets'

const base = {
  name: 'Power', capability_type: 'power' as const, enabled: true, agent_id: null, resource_id: null, provider_key: '', json: '{}',
}

describe('capabilityPayload', () => {
  it('builds a server-hosted DD power configuration with numeric fields', () => {
    const payload = capabilityPayload({
      ...base,
      backend: 'dd',
      config: {
        base_url: 'http://dd:5003', hub_mac: 'AA:BB:CC:DD:EE:FF', node_id: '1', endpoint: '2',
        api_key_env: 'TARGETHUB_DD_API_KEY', cycle_delay_seconds: '3', confirm_timeout_seconds: '',
      },
    })
    expect(payload).toEqual({
      name: 'Power', capability_type: 'power', enabled: true, provider_key: null, agent_id: null, resource_id: null,
      provider_config: {
        driver: 'dd', base_url: 'http://dd:5003', hub_mac: 'AA:BB:CC:DD:EE:FF', node_id: 1, endpoint: 2,
        api_key_env: 'TARGETHUB_DD_API_KEY', cycle_delay_seconds: 3,
      },
    })
  })

  it('maps Agent-backed capabilities to agent and resource ids without a driver', () => {
    const payload = capabilityPayload({ ...base, capability_type: 'serial', backend: 'agent', agent_id: 'a1', resource_id: 'r1', config: { driver: 'dd' } })
    expect(payload).toMatchObject({ agent_id: 'a1', resource_id: 'r1', provider_config: {} })
  })

  it('rejects invalid JSON for custom bridges', () => {
    expect(() => capabilityPayload({ ...base, capability_type: 'jlink', backend: 'custom', json: '{oops', config: {} })).toThrow(/not valid JSON/)
  })
})
