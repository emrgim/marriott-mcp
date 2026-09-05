# BUG-001 — OAuth token ufficiale 404

**Quando:** 2026-09-05  
**Sintomo:** `POST https://devportalprod.marriott.com/oauth/token` con `grant_type=client_credentials` → **HTTP 404**.

**Impatto:** nessun login consumer Bonvoy via API partner.

**Ricerca:** portal Akana/Atmosphere; OpenAPI Evangelist dichiara `tokenUrl` ma spec developer-api è 404. Login Bonvoy ufficiale è form web (email/member number + password + MFA), non client_credentials.

**Soluzione:** non usare il portal. Mini-server proprio + sessione browser su marriott.com.

**Esito:** applicata (vedi `src/`).
