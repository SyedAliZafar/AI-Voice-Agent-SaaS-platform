"""Industry modules: qualifying questions, vocabulary, and industry-specific objection
rows for each vertical being cold-called.

To add a new industry: add one entry to INDUSTRIES below. Nothing else in the module
system needs to change — compose.py and every style/service combination picks it up
automatically.
"""

HVAC_SOLAR = {
    "key": "hvac_solar",
    "label": "HVAC / Solar",
    # Verbatim from frontend/dashboardDesiging/hvac-solar-outbound-knowledge-v1.md —
    # this is the one leaf with a real call transcript behind it, don't redrift it.
    "qualifying_flow": """\
1. How do you currently handle calls when your team's on a job or it's after hours? \
(voicemail / answering service / front desk / nothing)
2. Roughly how many calls do you think you miss in a week, especially nights/weekends?
3. What's an average job worth to you — so a missed emergency call actually costs \
something concrete?
4. Do you have a website or marketing running that generates leads, and do those leads \
get followed up quickly?
5. Team size — is admin/dispatch handled by you, a family member, or dedicated staff?\
""",
    "vocabulary": """\
**HVAC:** no-heat/no-cool emergency call, seasonal surge (summer AC / winter furnace), \
service call vs. install vs. maintenance contract, dispatch, ticket value.

**Solar:** install pipeline, permitting/interconnection timeline, residential vs. \
commercial, system size (kW), incentive/tax credit questions, roof/shading \
qualification, financing credit check.

Wrong vocabulary here is an instant tell that this is a generic bot, not a specialist \
system — this is a cheap win, get it right.\
""",
    "extra_objection_rows": "",
    "validated": True,
}

DENTIST = {
    "key": "dentist",
    "label": "Dentist",
    "qualifying_flow": """\
1. How do calls get handled when the front desk is busy, at lunch, or after hours? \
(voicemail / answering service / just missed)
2. Roughly how many of those calls do you think turn into a missed new-patient booking \
or a rescheduled appointment, per week?
3. What's a new patient — or a typical treatment plan — worth to you, so a missed call \
has a real number attached?
4. Do you run any marketing or online booking that generates leads, and do those get \
followed up same-day?
5. Front desk team size — is it one person covering everything, or dedicated staff?\
""",
    "vocabulary": """\
**Dentistry:** new patient intake, hygiene recall, treatment plan acceptance, insurance \
verification / in-network vs. out-of-network, no-show rate, associate dentist, \
hygienist schedule, same-day emergency (toothache/broken tooth).

Wrong vocabulary here is an instant tell that this is a generic bot, not a specialist \
system — this is a cheap win, get it right.\
""",
    "extra_objection_rows": (
        '| "Our patients need to talk to a real person about their care" | Position as '
        "front-desk overflow for scheduling/intake only — clinical questions still route "
        "to staff, this just catches the call that would otherwise go to voicemail. |"
    ),
    "validated": False,
}

CAR_RENTALS = {
    "key": "car_rentals",
    "label": "Car Rentals",
    "qualifying_flow": """\
1. How do you handle reservation calls when the counter's busy or it's after hours — \
voicemail, an answering service, or do they just get missed?
2. Roughly how many reservation or extension calls do you think you miss per week, \
especially evenings and weekends?
3. What's an average rental worth to you, so a missed booking call has a real number \
attached to it?
4. Do you run any marketing or online booking that generates leads, and do those get \
followed up quickly?
5. Team size — is the counter/phone covered by one person, a rotating team, or dedicated \
dispatch/reservations staff?\
""",
    "vocabulary": """\
**Car rentals:** fleet utilization, reservation lead time, rate class, damage waiver, \
one-way rental, corporate account, peak-season surge pricing, no-show/cancellation \
policy, roadside/extension call.

Wrong vocabulary here is an instant tell that this is a generic bot, not a specialist \
system — this is a cheap win, get it right.\
""",
    "extra_objection_rows": (
        '| "Reservations need a real person to check the fleet/availability" | Position '
        "as capturing the request and qualifying it (dates, vehicle class, pickup "
        "location) even after hours, so nothing is lost — a human confirms availability "
        "and finalizes, this just stops the call from going to voicemail in the first "
        "place. |"
    ),
    "validated": False,
}

INDUSTRIES = {
    "hvac_solar": HVAC_SOLAR,
    "dentist": DENTIST,
    "car_rentals": CAR_RENTALS,
}
