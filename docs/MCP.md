# MCP protocol notes

Self-host. Streamable HTTP + OAuth 2.1 PKCE when you expose the server on HTTPS.

## Clients

- HTTPS only for remote connectors (no `localhost` URL to cloud agents).
- Transport: Streamable HTTP on `/` and `/mcp`.
- `Accept: application/json, text/event-stream`.
- OAuth PKCE; well-known routes unauthenticated; MCP routes Bearer.
- Short tool list. `serverInfo` + `instructions` describe the surface.

## MCP

- Protocol versions: 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05.
- Tool annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`.
- Results: `content` + `structuredContent` + `isError`.
- Prompts: `stays_overview`, `account_status`.
- `ping`, `logging/setLevel`.

## Skills (SEP-2640)

Draft extension `io.modelcontextprotocol/skills` (`directoryRead: true`).

- `skills/list` / `skills/get`
- Files: `skill://marriott-stays/SKILL.md`, `skill://marriott-reservations/SKILL.md`
- `resources/read`, `resources/directory/read`
- Fallback tools: `marriott_skills_list`, `marriott_skills_get`

Digests: `sha256:` + 64 lowercase hex of raw bytes.

## Writes + elicitation

Tools: `marriott_reservation_create`, `marriott_reservation_modify`, `marriott_reservation_cancel`.

A write never executes until `elicitation/create` returns `action=accept` and `confirm=true`.

1. Client calls a write tool.
2. Server keeps the POST open as SSE and sends `elicitation/create` (form, boolean `confirm`).
3. User confirms or cancels (client UI or `/confirm/{id}`).
4. Client POSTs the JSON-RPC result for that elicitation id.
5. Only then Playwright runs; the original `tools/call` result follows on the same stream.

Card data is never requested via elicitation. Create aborts if Marriott shows a card form.
