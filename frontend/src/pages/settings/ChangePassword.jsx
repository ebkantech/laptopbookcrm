import { useState } from "react";
import { KeyRound } from "lucide-react";
import { api } from "../../lib/api";
import { apiErrors } from "./errors";
import { Alert, PasswordInput } from "./StaffUi";
import "./staff.css";

/*
 * Settings > My password -- every signed-in account. POSTs to
 * /users/me/change-password/, which always acts on the requesting account,
 * verifies the current password, runs Django's password validators, signs
 * out every other session and returns fresh tokens for this one.
 */
const MIN_LENGTH = 10; // AUTH_PASSWORD_VALIDATORS MinimumLengthValidator -- the server enforces it

export default function ChangePassword() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState("");
  const set = (k) => (v) => { setForm((f) => ({ ...f, [k]: v })); setErrors((e) => ({ ...e, [k]: undefined, _form: undefined })); };

  const submit = async (e) => {
    e.preventDefault();
    setDone("");
    const local = {};
    if (!form.current_password) local.current_password = "Enter your current password.";
    if (form.new_password.length < MIN_LENGTH) local.new_password = `Use at least ${MIN_LENGTH} characters.`;
    if (form.new_password !== form.confirm_password) local.confirm_password = "The two new passwords don't match.";
    if (Object.keys(local).length) { setErrors(local); return; }
    setSaving(true);
    try {
      const res = await api.post("/users/me/change-password/", form);
      api.adoptTokens(res.access, res.refresh);
      setForm({ current_password: "", new_password: "", confirm_password: "" });
      setErrors({});
      setDone(res.detail || "Your password has been changed.");
    } catch (err) {
      setErrors(apiErrors(err, "Couldn't change your password."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="st">
      <form className="st-card" onSubmit={submit} noValidate>
        <div>
          <h2 className="st-title flex items-center gap-2"><KeyRound size={18} aria-hidden="true" />Change password</h2>
          <p className="st-desc">
            Choose at least {MIN_LENGTH} characters that aren't a common password, all numbers, or similar to your name or username.
            Changing it signs you out on every other device.
          </p>
        </div>
        {done && <Alert tone="ok">{done}</Alert>}
        {errors._form && <Alert>{errors._form}</Alert>}
        <PasswordInput label="Current password" value={form.current_password} onChange={set("current_password")} error={errors.current_password} autoComplete="current-password" />
        <PasswordInput label="New password" value={form.new_password} onChange={set("new_password")} error={errors.new_password} hint={`At least ${MIN_LENGTH} characters.`} />
        <PasswordInput label="Confirm new password" value={form.confirm_password} onChange={set("confirm_password")} error={errors.confirm_password} />
        <div className="flex justify-end">
          <button type="submit" className="st-btn" data-variant="primary" disabled={saving}>{saving ? "Saving…" : "Change password"}</button>
        </div>
      </form>
    </div>
  );
}
