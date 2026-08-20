const STEPS = [
  {
    n: "01",
    title: "Describe the agent",
    body: "Answer a handful of questions — who you’re calling, what you’re offering, how pushy to be. The builder turns that into a full call playbook: opener, qualifying questions, objection handling.",
  },
  {
    n: "02",
    title: "Test it by text",
    body: "Chat with the agent before it ever dials. The sandbox runs the exact prompt the phone call would use, so what you read is what the caller hears — no telephony, no cost.",
  },
  {
    n: "03",
    title: "Put it on the phone",
    body: "One click provisions the agent on Retell and dials. You watch the transcript stream in live, and the call outcome lands in your history whether or not the webhook made it back.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="border-t border-slate-200 bg-slate-50">
      <div className="mx-auto w-full max-w-6xl px-5 py-16 md:px-8 md:py-20">
        <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-slate-900">
          From an idea to a ringing phone, in one sitting
        </h2>
        <p className="mt-3 max-w-2xl text-slate-600">
          No prompt engineering, no Retell dashboard tab-switching, no glue code.
        </p>

        <ol className="mt-10 grid gap-5 md:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.n} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
              <span className="font-mono text-xs font-semibold tracking-wider text-brand-600">
                {s.n}
              </span>
              <h3 className="mt-3 text-base font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
