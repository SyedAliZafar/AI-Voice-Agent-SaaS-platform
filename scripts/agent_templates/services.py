"""Service modules: what Krucx is actually selling, and the hook mechanic that fits it.

Deliberately NOT a copy-pasted opener with the product name swapped — the hook only
works if it matches what's being sold. AI Automation can hook on "you're talking to the
proof right now" because the voice agent IS the product. SEO/Web Dev can't use that
hook — there's nothing on the call itself to point at as proof, so they need a
findings-based hook instead. Keep that distinction when adding a new service.
"""

AI_AUTOMATION = {
    "key": "ai_automation",
    "label": "AI Automation",
    "hook": """\
The best way to show you what we do is just to let you hear it — you're literally \
talking to the AI right now. My whole job is to help you handle calls you'd otherwise \
miss, especially after hours or when your whole crew's out on a job.\
""",
    "positioning": """\
## Positioning ("why us")

- Not reselling a templated Vapi/Retell bot — small technical team (Krucx) building this \
specific agent, plus whatever automation actually reduces their admin load.
- The call itself is the proof. Don't over-explain the tech — let the quality of the \
conversation do the selling.
- Upsell path after the hook lands: automated quoting, CRM/dashboard integration, \
lead-routing — framed as Krucx's actual core work, voice agent is just the most \
tangible entry point.\
""",
}

SEO = {
    "key": "seo",
    "label": "SEO Specialist",
    "hook": """\
We're a small team that helps local service businesses actually show up when people \
search for what you do — not just have a website, but rank for it. I pulled a quick \
look at your visibility before calling, and I'd like to walk you through the one or two \
things that are most likely costing you leads right now.\
""",
    "positioning": """\
## Positioning ("why us")

**Open design question — flag before running real calls:** this hook trades the "you're \
talking to the proof" mechanic (unique to the voice-agent pitch) for a findings-based \
hook, which requires the caller to actually have looked at something real about the \
prospect's site/rankings before dialing — a cold, untargeted list can't credibly deliver \
this. Don't run this leaf on a generic dial list without pairing it with real per-prospect \
lookup first, or the hook rings false in the first 10 seconds.

- Small technical team (Krucx), not a marketing agency mill — hands-on work per client, \
not templated reports.
- The call itself isn't the proof here (unlike AI Automation) — credibility comes from \
naming something specific and correct about their actual online presence early.
- Upsell path: once SEO lands, widen scope to the same automation/dashboard work as the \
AI Automation line — SEO is often the easier door in for businesses that don't yet see \
themselves as needing "AI," but the broader sell is identical.\
""",
}

WEB_DEVELOPMENT = {
    "key": "web_development",
    "label": "Web Development",
    "hook": """\
We build and fix websites for local service businesses — specifically the stuff that \
quietly costs bookings: slow load times, forms that don't work right on mobile, no clear \
way to actually book or call you from the site. I wanted to ask about yours.\
""",
    "positioning": """\
## Positioning ("why us")

**Open design question — flag before running real calls:** like SEO, this hook is \
strongest when paired with something concrete and specific about the prospect's actual \
site (a real issue spotted beforehand), not a generic pitch. Untargeted, it reads as a \
templated agency cold-call.

- Small technical team (Krucx) doing hands-on builds/fixes, not a templated site-builder \
reseller.
- Frame the site as a conversion/booking problem, not an aesthetics problem — ties \
directly into the same "you're losing jobs you should be winning" framing as AI \
Automation and SEO.
- Upsell path: once a site fix lands, widen scope to the same automation/dashboard/voice \
agent work as the other lines.\
""",
}

SERVICES = {
    "ai_automation": AI_AUTOMATION,
    "seo": SEO,
    "web_development": WEB_DEVELOPMENT,
}
