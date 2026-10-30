import { useState } from "react";
import { api } from "../../lib/api";
import { Alert, Dialog } from "../settings/StaffUi";
import "../settings/staff.css";

/*
 * Activate / deactivate one shop or channel (POST /stock-points/<id>/set-status/).
 * Superuser and administrators only -- the backend refuses anyone else
 * (catalog.status). Only the status changes: its history, stock and staff
 * links stay exactly as they are.
 */
export default function StoreStatusDialog({ store, onClose, onDone }) {
  const deactivating = store.is_active !== false;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const saved = await api.post(`/stock-points/${store.id}/set-status/`, { is_active: !deactivating });
      onDone(saved);
    } catch (err) {
      setError(err.message || "Couldn't change the status. Please try again.");
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={deactivating ? `Deactivate ${store.name}?` : `Reactivate ${store.name}?`} busy={busy} onClose={onClose}
      labelledBy="sl-status-title"
      footer={<>
        <button type="button" className="st-btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="st-btn" data-variant={deactivating ? "danger" : "primary"} onClick={submit} disabled={busy}>
          {busy ? "Saving…" : deactivating ? "Deactivate" : "Reactivate"}
        </button>
      </>}
    >
      <div className="st-grid">
        {error && <Alert>{error}</Alert>}
        {deactivating ? (
          <>
            <Alert tone="warn">
              <b>New operations will be blocked here</b> — no new sales or rent invoices, repair tickets, stock additions,
              rentals issued from its stock, or staff assignments.
            </Alert>
            <p className="st-note">
              Everything already recorded stays: invoices and payments, repairs, rentals, stock balances, staff and reports.
              Existing invoices can still be settled, refunded or cancelled and existing repairs and rentals completed.
              It stays listed here, and you can reactivate it at any time.
            </p>
          </>
        ) : (
          <p className="st-note">
            {store.name} will accept new sales, repairs, rentals, stock and staff assignments again, under the usual rules.
            Nothing that was refused while it was inactive is replayed.
          </p>
        )}
      </div>
    </Dialog>
  );
}
