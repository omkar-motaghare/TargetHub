# Roadmap

## Done in 0.2.0

Reservations with policy, extend, reserve-by-tag, waitlist and calendar · roles admin/user/viewer, refresh and
API tokens · WebSocket serial console with transcripts · DD power from the server · HTTP power · GPIO and
deploy on agents · Windows agents · notifications and Slack/Teams/generic webhooks · Windows server installer ·
CI with PostgreSQL, Windows and Docker jobs · multi-arch image release workflow · full documentation.

## Next (proposed priorities)

1. **Field validation**: run the [manual checklist](../MANUAL_VERIFICATION_CHECKLIST.md) on real DD
   hardware, a Raspberry Pi with relays and a Windows agent; fix what differs.
2. ~~**SSH/Telnet access to targets**~~ *(done, unreleased: agent tunnels bound to the session, `targethub tunnel`)*
3. ~~**Debugger integration**~~ *(done, unreleased: the same tunnel starts an OpenOCD/J-Link GDB server for the session; VS Code `miDebuggerServerAddress`)*
4. ~~**Artifact upload**~~ *(done, unreleased: local disk storage and the deploy panel upload; S3-compatible storage still to do)*
5. ~~**Board health checks**~~ *(done, unreleased: API, scheduler and Admin → Health checks)*
6. ~~**Usage reports**~~ *(done, unreleased: Admin → Reports with CSV by target, tag, user; per-team views and charts still to do)*
7. **Teams / projects**: group users and restrict targets per team; per-team policies.
8. **SSO**: OIDC (Azure AD/Entra ID, Google, Keycloak) and LDAP, alongside local accounts.
9. **Recording console sessions for replay** and searchable transcripts.
10. **Plugin interface** for third-party power and debug providers without forking the server.

Have a different priority? Open an issue describing the lab workflow it unblocks.
