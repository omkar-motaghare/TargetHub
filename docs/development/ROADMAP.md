# Roadmap

## Done in 0.2.0

Reservations with policy, extend, reserve-by-tag, waitlist and calendar · roles admin/user/viewer, refresh and
API tokens · WebSocket serial console with transcripts · DD power from the server · HTTP power · GPIO and
deploy on agents · Windows agents · notifications and Slack/Teams/generic webhooks · Windows server installer ·
CI with PostgreSQL, Windows and Docker jobs · multi-arch image release workflow · full documentation.

## Next (proposed priorities)

1. **Field validation**: run the [manual checklist](../MANUAL_VERIFICATION_CHECKLIST.md) on real DD
   hardware, a Raspberry Pi with relays and a Windows agent; fix what differs.
2. **SSH/Telnet access to targets** through the agent (port forwarding bound to the session), so
   network-booted boards can be reached without exposing them.
3. **Debugger integration**: J-Link / OpenOCD GDB server started by the agent for the session, reachable
   through a session-scoped tunnel; VS Code launch configuration.
4. **Artifact upload**: upload firmware to the server (or S3-compatible storage) instead of hosting it
   elsewhere for deploy.
5. **Board health checks**: scheduled power-on + "expect boot banner" checks that put a failing board into
   maintenance automatically.
6. **Usage reports**: utilisation per target/tag/team, idle reservations, waitlist times (CSV and charts).
7. **Teams / projects**: group users and restrict targets per team; per-team policies.
8. **SSO**: OIDC (Azure AD/Entra ID, Google, Keycloak) and LDAP, alongside local accounts.
9. **Recording console sessions for replay** and searchable transcripts.
10. **Plugin interface** for third-party power and debug providers without forking the server.

Have a different priority? Open an issue describing the lab workflow it unblocks.
