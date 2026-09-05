# Marriott MCP

**Your Marriott Bonvoy account, as tools an AI agent can actually use.**

Marriott MCP is a [Model Context Protocol](https://modelcontextprotocol.io/) server that signs into *your* marriott.com session and exposes it to clients such as Claude, ChatGPT, Cursor, or Grok.

It is **not** Marriott’s partner/CRS API. There is no public consumer API for points, elite nights, or trips. This server drives a real Chrome profile the same way you would, then wraps that session as MCP tools, resources, and skills.

Clone it, add Bonvoy credentials (`.env` **or** the login page the MCP opens — never in Grok chat), run it on your machine.

> Unofficial project. Not affiliated with, endorsed by, or maintained by Marriott International.

---

## What you get

| Surface | What it does |
| --- | --- |
| **Read** | Account, trips, stay history, **property search + availability** (URLs and dates from MCP, not the web) |
| **Write** | Create, modify, and cancel reservations |
| **Human gate** | Every write sends `elicitation/create` and **waits**. Nothing is booked or cancelled until you press Confirm |
| **Skills** | Agent Skills over MCP ([SEP-2640](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640)): `skills/list`, `skills/get`, files on `skill://` |
| **Transport** | stdio for local agents, Streamable HTTP + OAuth 2.1 PKCE for remote connectors |

Write tools never collect card numbers, CVV, or passwords through elicitation. If Marriott’s checkout asks for a card, the flow aborts.

---

## How it works

```
AI client  ── MCP (stdio or HTTPS) ──►  Marriott MCP
                                            │
                                            ▼
                                   persistent Chrome
                                   (your Bonvoy session)
                                            │
                                            ▼
                                      marriott.com
```

Akamai blocks bare HTTP from datacenter IPs. A headed Chrome profile with a normal login is the reliable path.

**Writes** do not run when the model “says confirm.” The server pauses the tool, emits a nested `elicitation/create` (Confirm / Cancel). Decline, cancel, or timeout → `changed: false`, Playwright never starts the mutation.

---

## Tools

**Read**

- `marriott_status` — signed in, page, first name
- `marriott_open` / `marriott_login` — session
- `marriott_me` — points, elite, nights
- `marriott_trips` — upcoming reservations
- `marriott_activity` — activity page
- `marriott_stays` — stay history (`months` default **240**)
- `marriott_search` — hotels for destination + dates (`property_id`, official URL)
- `marriott_availability` — rates + property URL for one hotel
- `marriott_page` — rooms, prices, confirmation number, structured errors
- `marriott_click` / `marriott_fill` / `marriott_dismiss` — interact (no cards/captcha)
- `marriott_goto` — marriott.com URLs only

**Write** (elicitation required)

- `marriott_reservation_create`
- `marriott_reservation_modify`
- `marriott_reservation_cancel`
- `marriott_book` — search → room → guest; Grok asks in chat, then second call with `user_said`

**Skills fallback** (if the client has no `skills/list` yet)

- `marriott_skills_list`
- `marriott_skills_get`

**Bugs** (saved on the MCP host, secrets stripped)

- `marriott_report_bug` — title, what happened, tool, arguments, log
- `marriott_bugs_list` / `marriott_bugs_get`

Manuals ship next to the tools:

- `skill://marriott-stays/SKILL.md`
- `skill://marriott-reservations/SKILL.md`

---

## Run your own copy

Requires Python 3.11+, Google Chrome, and a display (headed Chrome).

```bash
git clone https://github.com/emrgim/marriott-mcp.git
cd marriott-mcp
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chrome
```

Bonvoy sign-in (pick one):

- `.env` with `MARRIOTT_EMAIL` / `MARRIOTT_PASSWORD`, or
- skip `.env`: the first Marriott tool sends an **elicitation URL**. Open `/login/{token}`, enter Bonvoy there. Never type the password in Grok.

### Local stdio (Claude Desktop, Cursor, Hermes, …)

```json
{
  "mcpServers": {
    "marriott": {
      "command": "/absolute/path/to/marriott-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/marriott-mcp/src/mcp_server.py"],
      "env": {
        "DISPLAY": ":0"
      }
    }
  }
}
```

On macOS, omit `DISPLAY` if Chrome can open windows normally.

### Streamable HTTP + OAuth (Grok custom connector, remote agents)

```bash
export MARRIOTT_PUBLIC_BASE=https://your-https-host.example
export MARRIOTT_GROK_MCP_HOST=127.0.0.1
export MARRIOTT_GROK_MCP_PORT=8099
export DISPLAY=:0
.venv/bin/python src/grok_http.py
```

Put HTTPS in front (reverse proxy or tunnel). Well-known OAuth and `/oauth/*` stay unauthenticated; MCP POST `/` and `/mcp` require a bearer token from PKCE.

Connector form (typical):

- Server URL: `https://your-https-host.example`
- Client ID: `grok`
- Client secret: empty
- Token auth: none (PKCE)
- Scope: `mcp:tools`

A systemd user unit template lives in `deploy/marriott-grok-mcp.service` — copy it and adjust paths.

---

## Environment

See `.env.example`. Never commit `.env`. Chrome profile and cookies stay in `.session/` (gitignored).

| Variable | Purpose |
| --- | --- |
| `MARRIOTT_EMAIL` | Bonvoy email or member number |
| `MARRIOTT_PASSWORD` | Bonvoy password |
| `MARRIOTT_PUBLIC_BASE` | Public HTTPS origin for OAuth + confirm links |
| `MARRIOTT_GROK_MCP_HOST` / `_PORT` | HTTP bind |
| `MARRIOTT_ELICIT_TIMEOUT` | Seconds to wait for Confirm (default 180) |

---

## Protocol notes

- MCP protocol versions: `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`
- Skills extension: `io.modelcontextprotocol/skills` with `directoryRead: true` (draft SEP-2640)
- Write path: nested `elicitation/create` on the Streamable HTTP SSE stream; optional `/confirm/{id}` page
- Confirming a write in chat is not enough. The button is.

More detail: [`docs/MCP.md`](docs/MCP.md).

---

## Safety

- Credentials live only in your `.env` and OS keychain-equivalent. This repo ships empty placeholders.
- Destructive tools are annotated `destructiveHint: true`.
- The server refuses unknown cancel/delete tool names.
- Do not point a public connector at an account you do not control.

---

## License

MIT. See [LICENSE](LICENSE).
