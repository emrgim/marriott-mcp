# Security

- Never commit `.env`. Chrome profiles and OAuth tokens stay in `.session/` (gitignored).
- This server acts as **your** Bonvoy session. Do not expose it on the public internet without TLS and OAuth, and do not share the process with people who should not operate that account.
- Write tools run only after MCP `elicitation/create` is accepted. Treat that confirmation UI as the authorization boundary.
- The server will not collect payment cards or passwords through elicitation.
- Unofficial software. You are responsible for complying with Marriott’s terms of use.
