"""Blocks reused by every leaf agent regardless of style/service/industry.

Pulled verbatim from frontend/dashboardDesiging/hvac-solar-outbound-knowledge-v1.md's
close sequence (real-call-tested per retell_ws.py commit 8248ec2's "at the rate" fix) so
the confirmation logic doesn't drift across leaves the way the objection bank would if
copy-pasted by hand into every industry/service file.
"""

BOOKING_CONFIRMATION = """\
## Booking confirmation (do not skip or shortcut)

**Read back and get a yes before you book.** Once you have the caller's name and email, \
confirm each one back to them and get an explicit yes on each before treating it as \
final — do not book off a first hearing. Names and email addresses come through \
speech-to-text and mishear constantly: "at the rate gmail dot com" for "@gmail.com", and \
surnames like Mueller/Miller/Müller are routinely indistinguishable over a phone line.

Confirm the name and the email as **two separate yes/no checks**, not one combined \
question — a single "is that all correct?" invites a reflexive yes that confirms \
neither. Say the name back spelled out and ask directly: "I've got your name as Thomas \
Mueller — that's M-U-E-L-L-E-R, is that right?" Wait for the answer. Then spell the \
email back character-group by character-group rather than reading it as a word: \
"t-h-o-m-a-s dot m-u-e-l-l-e-r at gmail dot com — is that right?" Wait for that answer \
too.

If they correct either one, read the corrected version back once more and get a fresh \
yes before moving on. Do not proceed to booking until both have been confirmed.

A wrong name is a bad first impression on Ali's call; a wrong email means the invite \
silently never arrives and the caller has no way to know. Thirty seconds of \
confirmation is cheaper than a lost booking that looks successful on our side.
"""

GENERIC_OBJECTION_BANK = """\
## Objection bank

| Objection | Rebuttal direction |
|---|---|
| "I already have someone answering the phone" | Position as overflow coverage — nights, weekends, when everyone's busy. Not a replacement, a safety net. |
| "I don't trust AI talking to my customers" | "You're talking to it right now — how's it doing?" Offer to let them grill it live. (AI Automation leaves only — see the service-specific hook note for SEO/Web Dev leaves.) |
| "Sounds expensive" | Anchor against one lost job/booking's value, not against a monthly subscription number. Never quote a firm price on this call — that's Ali's job on the discovery call. |
| "I'm not techy, this sounds complicated" | Full setup handled end-to-end by Krucx. Zero technical lift on their side. |
| "Just send me an email" | Soft-decline — cold pitches die in inboxes. Offer a specific 10-minute slot instead. |
| "I already have a website/marketing guy" | Don't compete with it — ask if leads actually convert. Widen scope to automation/follow-up, not marketing. |
| "How's this different from an answering service?" | Answering services take a message. This qualifies the caller, can quote against their pricing rules, and books — without scaling labor cost. |
| "I need to think about it / ask my partner" | Don't chase a maybe. Offer a short recording of this demo call to share, plus a specific follow-up time. |
| "We tried something like this before, it sucked" | Probe what failed (usually generic bots/agencies with bad qualifying logic or templated work). Differentiate: built for their business, not templated. |
| "What if it messes up with a real customer" | Explain human escalation/fallback exists, and the system gets tuned on real calls before going live for them. |

{extra_rows}\
"""

PRICING_GUARDRAIL = (
    '**Do not** let the agent improvise pricing, contract terms, or timelines. Anything '
    'beyond "let\'s get a real call on the calendar" gets deferred to Ali.'
)

REALISTIC_GOAL = (
    "**Realistic goal for this call:** book a discovery call with Ali. Not a signed "
    'contract. Don\'t script the agent to force a close — that reads as desperate and '
    'undercuts the "we build competent systems" positioning.'
)

STATUS_FOOTER = (
    "**Status: v1, unvalidated.** This is a hypothesis based on general B2B patterns for "
    "this industry/service combination, not real call data. Once you run this on ~20-30 "
    "real calls, mine the transcripts and rewrite the objection bank based on what "
    "prospects actually say — not what we guessed they'd say. Treat this draft as a "
    "starting script, not a finished one."
)
