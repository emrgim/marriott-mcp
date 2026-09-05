# BUG-013 — Chrome profile already in use

**Quando:** probe mentre `marriott-grok-mcp.service` tiene `verify-chrome-profile`.

**Sintomo:** `launch_persistent_context: Opening in existing browser session`.

**Fix previsto:** un solo processo Chrome (il servizio Grok). Probe/CLI parlano HTTP MCP, non un secondo Playwright.
