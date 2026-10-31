import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { api } from "../lib/api";
import { APP_NAME } from "../lib/theme";
import { apiErrors } from "./settings/errors";
import { Alert, PasswordInput } from "./settings/StaffUi";
import "./settings/staff.css";

/*
 * Public page behind a one-time password-setup link
 * (/set-password/<uid>/<token>), created by an administrator's Reset
 * Password or for a new account. The link works once and expires after
 * 24 hours -- the server checks both (accounts.views.PasswordSetupView).
 */
export default function SetPassword({ uid, token }) {
  const path = `/auth/password-setup/${encodeURIComponent(uid)}/${encodeURIComponent(token)}/`;
  const [state, setState] = useState({ status: "checking", username: "", detail: "" });
  const [form, setForm] = useState({ new_password: "", confirm_password: "" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api.publicGet(path)
      .then((d) => alive && setState({ status: "ready", username: d.username, detail: "" }))
      .catch((e) => alive && setState({ status: "invalid", username: "", detail: e.body?.detail || "This link can't be used." }));
    return () => { alive = false; };
  }, [path]);

  const submit = async (e) => {
    e.preventDefault();
    if (form.new_password !== form.confirm_password) { setErrors({ confirm_password: "The two passwords don't match." }); return; }
    setSaving(true);
    try {
      await api.publicPost(path, form);
      setState((s) => ({ ...s, status: "done" }));
    } catch (err) {
      const errs = apiErrors(err, "Couldn't set your password.");
      if (err.body?.valid === false) setState({ status: "invalid", username: "", detail: errs._form });
      else setErrors(errs);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="st-public">
      <div className="st-card">
        <div>
          <h1 className="st-title flex items-center gap-2"><KeyRound size={18} aria-hidden="true" />Set your {APP_NAME} password</h1>
          {state.status === "ready" && <p className="st-desc">For the account <b className="st-mono">{state.username}</b>. This link works once.</p>}
        </div>
        {state.status === "checking" && <p className="st-note">Checking your link…</p>}
        {state.status === "invalid" && <Alert>{state.detail}</Alert>}
        {state.status === "done" && (
          <>
            <Alert tone="ok">Your password has been set. You can now sign in.</Alert>
            <a className="st-btn" data-variant="primary" href="/">Go to sign in</a>
          </>
        )}
        {state.status === "ready" && (
          <form onSubmit={submit} noValidate className="grid gap-3">
            {errors._form && <Alert>{errors._form}</Alert>}
            <PasswordInput label="New password" value={form.new_password} autoFocus error={errors.new_password}
              onChange={(v) => { setForm((f) => ({ ...f, new_password: v })); setErrors({}); }} hint="At least 10 characters; not a common password." />
            <PasswordInput label="Confirm new password" value={form.confirm_password} error={errors.confirm_password}
              onChange={(v) => { setForm((f) => ({ ...f, confirm_password: v })); setErrors({}); }} />
            <button type="submit" className="st-btn" data-variant="primary" disabled={saving}>{saving ? "Saving…" : "Set password"}</button>
          </form>
        )}
      </div>
    </div>
  );
}
