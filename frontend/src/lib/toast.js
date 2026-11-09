// App-wide pop-up messages: toast.success("Ticket RPR-1093 created").
// <Toaster /> (components/Toaster.jsx), mounted once in the app shell, shows them.
const EVENT = "crm:toast";
let next = 1;

function emit(kind, text, detail = "") {
  if (!text || typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { id: next++, kind, text, detail } }));
}

export const toast = {
  success: (text, detail) => emit("success", text, detail),
  info: (text, detail) => emit("info", text, detail),
  error: (text, detail) => emit("error", text, detail),
};

export const TOAST_EVENT = EVENT;
