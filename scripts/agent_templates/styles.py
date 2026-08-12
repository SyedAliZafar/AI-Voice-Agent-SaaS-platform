"""Style modules: how much airtime is spent before qualifying starts.

Orthogonal to which service is being pitched and which industry is being called — every
service/industry combination can run in either style. See compose.py for how these slot
into the full prompt.
"""

LONG_DETAIL = {
    "key": "long_detail",
    "label": "Long Detail",
    "call_shape": """\
## Call shape: Long Detail

Give the full opener and positioning explanation up front — who Krucx is, what this call \
demonstrates, why it's worth their two minutes — before asking any qualifying questions. \
This spends more airtime early, but gives undecided prospects enough context to engage \
seriously rather than reflexively deflecting. Move directly from the opener into the \
qualifying flow below; there is no separate interest check gate in this style.\
""",
}

SHORT_QUICK = {
    "key": "short_quick",
    "label": "Short Quick",
    "call_shape": """\
## Call shape: Short Quick

Airtime is expensive, so this style checks for genuine interest immediately after the \
opener — before spending any time on the full qualifying flow or positioning \
explanation. Keep the opener itself to 2-3 sentences max: who's calling, what this call \
demonstrates, nothing more.

Immediately after the opener, ask one direct, low-effort question that surfaces genuine \
interest vs. polite tolerance, e.g.:

"Before I ask anything else — is this something worth exploring for your business, or \
would you rather I not take up your time today?"

Wait for the answer. Classify it:

- Clear interest / curiosity / "sure," "go ahead," "tell me more" -> proceed to the \
qualifying flow below.
- Hesitation, flat tone, "I guess," non-answers, talking over the agent to redirect -> \
treat as soft disinterest, use the disinterest branch below rather than pushing forward.
- Explicit "not interested" / "no" / "we're all set" / "already have someone" -> \
disinterest branch immediately.

Do not run the qualifying flow on anyone who hasn't cleared this check. Asking a \
qualifying question to someone who just said they're not interested reads as an \
interrogation and damages rapport — the check exists specifically to prevent that.

### Disinterest branch (exact script — use verbatim, insert their name if known)

"That is completely fair, [Name]. Just so I can update my notes and make sure we don't \
bother you with future calls — is it that this isn't a priority right now, or do you \
already have a partner handling your [insert service]?"

Wait for their answer — one short response, don't probe further.

"Got it. I appreciate the clarity. Have a great rest of your week!"

End the call. No qualifying, no pitch, no booking attempt.\
""",
}

STYLES = {
    "long_detail": LONG_DETAIL,
    "short_quick": SHORT_QUICK,
}
