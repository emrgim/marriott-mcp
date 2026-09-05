# Research: Marriott.com / Bonvoy account access

Goal: read **your own** account (points, status, trips, activity).
Not a B2B booking CRS, not third-party scraping of other guests.

## 1. Official partner API (not a personal account API)

Portal: Marriott developer portal (Akana/Atmosphere).

Third-party catalogs list stubs such as availability, properties, reservations with client_credentials. Those credentials are partner CRS apps, **not** a Bonvoy member login.

**Conclusion:** the official API does not expose member points, tier, or My Trips.

## 2. marriott.com (account surface)

- Sign-in → My Trips
- Activity: `/loyalty/myAccount/activity.mi`
- Lookup: `/reservation/lookupReservation.mi`

Site: Next.js + Apollo GraphQL. Public shop queries exist for rates, not loyalty.

**Akamai Bot Manager:** datacenter curl to `www.marriott.com` is typically HTTP 403. A real browser session is required.

Bonvoy MFA: device registration on new browsers.

**Conclusion:** headed Chrome + persistent profile.

## 3. Architecture

```
Agent ── MCP ──► marriott-mcp
                    │
                    ▼
              persistent Chrome
                    │
                    ▼
              marriott.com
```
