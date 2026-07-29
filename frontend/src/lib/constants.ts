// Tenant identity is no longer sent by the browser. The backend derives tenant_id from
// the bearer token's claims (backend/api/deps.py:get_current_tenant), so passing it as a
// query param — which is what DEMO_TENANT_ID used to be for — would be both redundant and
// forgeable.
//
// For local dev, mint a token for the demo tenant with:
//     uv run python scripts/dev_token.py
// then put it in frontend/.env.local as NEXT_PUBLIC_DEV_AUTH_TOKEN (see lib/api.ts).
export const DEMO_TENANT_ID = "11111111-1111-1111-1111-111111111111";
