"use client";

import { useState } from "react";

import { PlusIcon } from "@/components/icons";
import { Button, Card, Field, TextArea, TextInput } from "@/components/ui";
import { api, getApiErrorMessage } from "@/lib/api";

/** Manual entry for a warm lead (Bark.com or otherwise) — the operator types in what
 * came in, and the lead lands paused (ADR-011: never auto-armed on create). Fields
 * are deliberately generic; the backend's `details` JSON absorbs anything not called
 * out as its own column, so this list can grow without a schema change.
 */
export function LeadCreateForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [businessName, setBusinessName] = useState("");
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [serviceRequested, setServiceRequested] = useState("");
  const [budget, setBudget] = useState("");
  const [requestText, setRequestText] = useState("");
  const [notes, setNotes] = useState("");

  function reset() {
    setBusinessName("");
    setContactName("");
    setPhone("");
    setEmail("");
    setCity("");
    setCountry("");
    setServiceRequested("");
    setBudget("");
    setRequestText("");
    setNotes("");
  }

  async function submit() {
    setSaving(true);
    setError("");
    try {
      await api.post("/leads", {
        business_name: businessName || null,
        contact_name: contactName || null,
        phone,
        email: email || null,
        city: city || null,
        country: country || null,
        service_requested: serviceRequested || null,
        budget: budget || null,
        request_text: requestText || null,
        notes: notes || null,
        source: "bark",
      });
      reset();
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(getApiErrorMessage(err, "Failed to add lead."));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button icon={<PlusIcon width={16} height={16} />} onClick={() => setOpen(true)}>
        Add lead
      </Button>
    );
  }

  return (
    <Card className="mb-6 p-5">
      <p className="mb-4 text-sm font-semibold text-slate-900">Add a Bark lead</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Business name">
          <TextInput value={businessName} onChange={(e) => setBusinessName(e.target.value)} />
        </Field>
        <Field label="Contact name">
          <TextInput value={contactName} onChange={(e) => setContactName(e.target.value)} />
        </Field>
        <Field label="Phone" hint="Required — this is who the scheduler will call.">
          <TextInput
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+491701234567"
          />
        </Field>
        <Field label="Email">
          <TextInput value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="City">
          <TextInput value={city} onChange={(e) => setCity(e.target.value)} />
        </Field>
        <Field label="Country">
          <TextInput value={country} onChange={(e) => setCountry(e.target.value)} />
        </Field>
        <Field label="Service requested">
          <TextInput
            value={serviceRequested}
            onChange={(e) => setServiceRequested(e.target.value)}
            placeholder="Boiler repair"
          />
        </Field>
        <Field label="Budget">
          <TextInput value={budget} onChange={(e) => setBudget(e.target.value)} />
        </Field>
      </div>

      <Field label="Their request, in their own words">
        <TextArea
          value={requestText}
          onChange={(e) => setRequestText(e.target.value)}
          rows={2}
        />
      </Field>

      <Field
        label="Your notes"
        hint="The per-lead holder — spoken on the call, and trusted over everything else above."
      >
        <TextArea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </Field>

      {error && <p className="mb-3 text-xs text-red-600">{error}</p>}

      <div className="flex gap-2">
        <Button onClick={submit} disabled={saving || !phone}>
          {saving ? "Saving…" : "Add lead"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            reset();
            setOpen(false);
          }}
        >
          Cancel
        </Button>
      </div>
    </Card>
  );
}
