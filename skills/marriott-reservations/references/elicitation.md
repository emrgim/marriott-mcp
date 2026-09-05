# Elicitation for Marriott writes

Transport: Streamable HTTP SSE (and stdio).

1. Client calls `tools/call` on a write tool.
2. Server sends a JSON-RPC **request** `elicitation/create` (form mode, boolean `confirm`) on the open stream. The original `tools/call` does not return yet.
3. Client shows Confirm / Cancel, or the user opens `/confirm/{elicit-id}` on this server.
4. Client POSTs `{ "jsonrpc":"2.0", "id": "<elicit-id>", "result": { "action": "accept"|"decline"|"cancel", "content": { "confirm": true } } }`.
5. Only then the server runs the Marriott.com flow and returns the `tools/call` result.

`action` values: accept, decline, cancel — same as the MCP elicitation spec.
