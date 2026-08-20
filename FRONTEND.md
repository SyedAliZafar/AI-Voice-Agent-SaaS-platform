# FRONTEND.md — UI structure and conventions

> **This started as a target-state document; the structural move described below has
> since happened** — `components/ui/`, `components/layout/`, and
> `components/features/{agents,calls,prospects,leads}/` all exist and match CONTEXT.md's
> structure tree. It stays the reference for the *conventions* (where a new component
> goes, tokens, fetching-in-hooks) rather than a still-pending migration. Where it
> says "today", that's current reality; where it says "target", read it as "the
> convention going forward" rather than "not built yet."

Stack: Next.js 14 (App Router) + React 18 + Tailwind + TypeScript, in `frontend/`.

## Target structure

`components/` used to be flat — 14 files, mixing generic primitives (`ui.tsx`, `form.tsx`),
app chrome (`AppShell`, `Sidebar`, `Topbar`), and domain features (`AgentBuilder`,
`LiveCallPanel`) at the same level. That's fine at 14 files and painful at 40, so it's
been split into:

```
frontend/src/
├── app/                      # routes only — thin, presentational
│   ├── layout.tsx            #   document + font only, NO app chrome
│   ├── page.tsx              #   public landing page (marketing)
│   └── (app)/                #   route group: everything behind the app chrome
│       ├── layout.tsx        #     wraps children in AppShell
│       └── dashboard|agents|calls|prospects|leads|settings/
├── components/
│   ├── ui/                   # generic primitives, one per file, zero domain knowledge
│   │   ├── Button.tsx        #   (split out of today's ui.tsx)
│   │   ├── Card.tsx
│   │   ├── Badge.tsx
│   │   ├── PageHeader.tsx
│   │   ├── EmptyState.tsx
│   │   ├── Skeleton.tsx
│   │   └── index.ts          # re-export, so imports stay `@/components/ui`
│   ├── layout/               # app chrome: AppShell, Sidebar, Topbar
│   └── features/             # domain components, grouped by resource
│       ├── agents/           #   AgentCard, AgentBuilder, Stepper, PromptEditor
│       ├── calls/            #   CallTable, TranscriptViewer, LiveCallPanel
│       ├── prospects/        #   Search/filter/group tree/detail panel + sandbox chat
│       ├── leads/            #   Create form/row/detail panel + stats (ADR-011)
│       ├── dashboard/        #   SetupChecklist, RetellStatus, SyncNotice
│       └── marketing/        #   landing page sections (Hero, Pricing, …)
├── hooks/                    # all data fetching lives here
└── lib/                      # api client, types, formatting, constants, workspace
```

## The `(app)` route group and the public landing page

`app/layout.tsx` used to wrap *everything* in `AppShell`, which meant every route got a
sidebar — fine while the app was dashboard-only, wrong the moment a public page exists.

Routes are now split into two groups. Parenthesised segments **don't affect URLs**:
`/dashboard` is still `/dashboard`, and no link or route needed changing.

- `app/layout.tsx` — `<html>`/`<body>`, the Inter font, `globals.css`. Nothing else.
- `app/page.tsx` — the marketing landing page at `/`, rendered with no app chrome. It's
  fully static; its only entry point into the product is a link to `/dashboard`.
- `app/(app)/layout.tsx` — wraps its children in `AppShell`. Every authenticated route
  lives under here.

**Rule: a new product page goes in `(app)/`. A new public page goes next to
`app/page.tsx`.** If you find yourself conditionally hiding the sidebar based on
`usePathname()`, that's the signal you've put a route in the wrong group.

The landing page's feature copy is deliberately constrained to things the product can
actually demonstrate on screen — see the comment in `features/marketing/FeatureGrid.tsx`.
Claims a screenshot can't back up are worse than a shorter list.

## Status badges read live state, never a literal

Settings' "Voice platform" card used to hardcode a green `Connected` badge. The dashboard
(`features/dashboard/RetellStatus`) does a real probe via `usePlatformAgents`, so a dead
Retell account showed **red on /dashboard and green on /settings** — and /settings is
where you'd go to check. Both now read the same hook.

The rule: **a badge or status line describing something outside the browser must be
derived from a request, not typed in.** If there's no data source for it yet, say what's
unknown rather than picking the optimistic label.

Its companion: **don't render a control that can't do anything.** The card's `Manage`
button had no handler. `RETELL_API_KEY` is a server env var, so there is no in-app
connect flow to build — the card now says where the key lives and what to edit, which is
the actually-actionable thing. Same reason the setup checklist's first step says "How"
instead of "Connect".

Still mocked on that page, and *not* covered by the rule above yet: the integrations list
and phone numbers are hardcoded arrays with local-only toggles, even though
`/api/integrations` is real. Wiring them is its own pass.

## The signed-in identity is mocked in exactly one place

Real auth isn't built (see the auth note at the bottom of this file). Until it is,
`lib/workspace.ts` is the **single** source for the workspace name, plan, and user —
Sidebar, Topbar, Settings and the Dashboard header all read it.

This used to be inline strings (`"Demo workspace"`, `"Free plan"`, a hardcoded `AZ`
avatar) retyped across components. **Don't reintroduce that**: when Clerk lands, the
migration should be replacing this module's export with a session hook and touching
nothing else.

The rule that decides where a component goes: **does it know what an Agent or a Call
is?** If no, it's `ui/`. If it's chrome around every page, it's `layout/`. Otherwise it's
`features/<resource>/`.

`ui.tsx` and `form.tsx` were the only files that bundled multiple components; both have
been split, with `components/ui/index.ts` re-exporting so import paths stayed short.

Also: `cx()` (the className joiner) used to be defined *and not exported* in `ui.tsx`, so no other
component could use it. It's now `lib/cx.ts`, exported.

## Design tokens — one source, not three

There are currently three overlapping sources of the same values:

1. `tailwind.config.ts` — a real, deliberate token set: `brand` 50–900 scale, custom
   `boxShadow` (`card`, `card-hover`, `focus`), `borderRadius` (`xl`, `2xl`), `fade-in`
   animation, Inter via `--font-inter`.
2. `app/globals.css` `:root` — CSS custom properties (`--bg`, `--surface`, `--border`,
   `--text`, `--muted`, `--accent`, `--accent-hover`, `--accent-tint`) that **partially
   duplicate** the above. `--accent: #4f46e5` *is* `brand-600`; `--accent-hover: #4338ca`
   *is* `brand-700`; `--accent-tint: #eef2ff` *is* `brand-50`.
3. Hardcoded repeats — `globals.css`'s `:focus-visible` writes
   `box-shadow: 0 0 0 3px rgb(99 102 241 / 0.25)` literally, which is exactly the
   `shadow-focus` token already defined in the Tailwind config. And the `.card` CSS class
   in `globals.css` overlaps the `Card` component in `ui.tsx`.

**Rule: `tailwind.config.ts` is the single source of truth for design tokens.** The CSS
custom properties should be either deleted (in favor of Tailwind utility classes) or
redefined *from* the Tailwind scale rather than restating hex values. Global CSS keeps
only what Tailwind genuinely can't express — base `body` styles, scrollbar styling,
`::selection`. A component that exists in `ui.tsx` should not also exist as a
`@layer components` class.

Why it matters concretely: rebranding today means changing the same indigo in three
places, and missing one is invisible until someone notices a stale accent in a focus ring.

## Data fetching stays out of pages

Today, page components do their own fetching inline — `dashboard/page.tsx` calls
`api.get<Call[]>("/calls", …)` inside a `useEffect` next to its JSX, and
`AgentBuilder.tsx` calls `fetch("/api/strategist", …)` alongside its form state.

**Target: `page.tsx` files and feature components are presentational; fetching lives in
`hooks/`**, alongside the existing `useWebSocket.ts` and `useCallMetrics.ts` (which
already follow this pattern — extend it, don't invent a second one). A hook owns the
loading/error/data triple; the component renders it.

This is what makes the components testable in isolation and stops the same
fetch-and-handle-error boilerplate being re-typed per page.

## Types are hand-synced with the backend — deliberately, for now

`lib/types.ts` mirrors `backend/schemas/*.py` by hand. There is no codegen (no
`openapi-typescript`, no `orval`), even though the backend serves an OpenAPI schema at
`/openapi.json`.

**Rule while this is hand-maintained: change both sides in the same commit.** The
"Add a field to an existing model" recipe in CONTEXT.md ends with `lib/types.ts` for
exactly this reason.

Known drift to be aware of: the frontend is in places *stricter* than the backend.
`Call.status` is a union (`"in_progress" | "resolved" | "escalated" | "failed"`) in
`lib/types.ts`, but `backend/schemas/call.py` types it as a bare `str`. The frontend union
is the better-documented contract — the fix is to tighten the backend to a `Literal` or
enum, not to loosen the frontend. Until then, don't assume the backend rejects an
unexpected status.

If the hand-syncing becomes a recurring source of bugs, generating `types.ts` from
`/openapi.json` is the escape hatch — but that's a real dependency, so don't add it
speculatively.

## `app/api/strategist/route.ts` — why a Next.js route exists at all

This is the one place the frontend has its own server-side endpoint instead of calling the
FastAPI backend, so it's worth explaining rather than leaving as a surprise.

It's the **"Strategist"** — a build-time co-pilot for the Agent Builder wizard. Two modes:
`research` (light enrichment on the target company — currently a stub in `enrichCompany()`,
marked as a seam for a real enrichment API) and `generate` (calls DeepSeek to produce the
finished sales `system_prompt` plus a pitch/objection playbook). It degrades gracefully:
missing key, non-OK response, or a parse failure all fall back to the deterministic
template in `lib/builder.ts`, so the wizard is never blocked.

It runs server-side (`runtime = "nodejs"`) specifically so `DEEPSEEK_API_KEY` never
reaches the browser — that's the legitimate reason it isn't a client-side call.

**Open question worth deciding deliberately:** it is *not* obviously the reason it isn't a
*backend* call. It duplicates LLM-calling logic that `backend/services/llm_service.py`
already owns, it holds a second copy of the DeepSeek credential, and it sits outside the
tenant-auth boundary that every `/api/*` route goes through (ADR-001). This is build-time,
not call-time, so it doesn't violate ADR-003 (which is about *runtime* tool execution) —
but if a second frontend-side LLM route ever appears, that's the signal to move this into
the backend instead.

## Conventions that are already working — keep them

- One component per file, PascalCase filename matching the export.
- Typed props via an explicit `interface`/type — no `any`, no untyped destructuring.
- Tailwind utility classes for styling; no CSS-in-JS, no per-component `.css` files.
- A single axios instance in `lib/api.ts` with the auth-token interceptor and the shared
  `getApiErrorMessage` error flattener — don't hand-roll `fetch` against the backend, use
  it. (The one exception is `/api/strategist`, which is same-origin Next, not the backend.)
- Auth token comes from `NEXT_PUBLIC_DEV_AUTH_TOKEN` or `localStorage.auth_token` — see
  RUN.md. Real Clerk login is unbuilt.

## Commands

```
cd frontend
npm install
npm run dev      # http://localhost:3000/dashboard
npm run build
npm run lint
```
