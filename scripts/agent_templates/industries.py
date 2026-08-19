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

ROOFING = {
    "key": "roofing",
    "label": "Roofing",
    # Leads on the estimate pipeline rather than generic missed calls: for roofers the
    # expensive loss isn't the call itself, it's the estimate that never got scheduled
    # before a competitor got on the roof first. Crew scheduling / labour tracking is
    # deliberately the last question, not the hook — it's an ops-software sell and
    # belongs in the upsell beat, not the first 30 seconds.
    "qualifying_flow": """\
1. When someone calls for an estimate while your crews are up on a job, how does that \
call get handled — office person, voicemail, or does it just get missed?
2. How long does it usually take from that first call to actually having an estimator \
at the property?
3. Roughly how many estimate requests do you think you lose in a week to slow follow-up \
or a competitor getting there first?
4. What's an average roof worth to you — so a missed estimate has a real number \
attached to it?
5. How do you handle crew scheduling and tracking hours across jobs right now — \
whiteboard, spreadsheet, texting the foreman, or dedicated software?\
""",
    "vocabulary": """\
**Roofing:** tear-off vs. overlay, squares, decking, underlayment, ridge/valley/\
flashing, dry-in, roof pitch, storey count, leak repair vs. full replacement, storm/hail \
damage, insurance claim, adjuster, supplement, permit and final inspection, material vs. \
workmanship warranty, material drop, crew vs. sub.

**Crew/ops side (upsell vocabulary, not opener vocabulary):** crew scheduling, foreman \
hours, job costing, day-of dispatch, weather delay reschedule.

Wrong vocabulary here is an instant tell that this is a generic bot, not a specialist \
system — this is a cheap win, get it right.\
""",
    "extra_objection_rows": (
        '| "You can\'t quote a roof over the phone" | Agree immediately — no price gets '
        "quoted. The agent captures what the estimator actually needs (leak vs. full "
        "replacement, roof age, storey count, insurance claim or cash) and books the "
        "inspection, so the estimator shows up already informed instead of the call "
        "dying in voicemail. |\n"
        '| "It\'s storm season, we\'re already slammed" | That\'s exactly when estimate '
        "calls go unanswered and land with whoever picks up first. Frame as capacity "
        "during the surge, not extra work on top of it. |\n"
        '| "We already use [job scheduling software]" | Don\'t compete with it — ask '
        "what happens to the call *before* a job exists in that system. The gap is "
        "intake and follow-up, not scheduling. |"
    ),
    "validated": False,
}

INDUSTRIES = {
    "hvac_solar": HVAC_SOLAR,
    "dentist": DENTIST,
    "car_rentals": CAR_RENTALS,
    "roofing": ROOFING,
}
