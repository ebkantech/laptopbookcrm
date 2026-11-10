// Voice typing helpers (components/DictateButton.jsx). Kept free of React and
// the browser so they can be tested.

export const DICTATION_LANGUAGES = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिंदी" },
];

/** The browser's speech recogniser, or null (Firefox / Safari on some versions / insecure http pages). */
export function recognizerClass(win = typeof window === "undefined" ? undefined : window) {
  if (!win) return null;
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
}

/**
 * Add spoken words to what's already typed: one space between them, a
 * capital at the start of a sentence, and never past maxLength.
 */
export function appendDictation(current, spoken, maxLength = Infinity) {
  const before = String(current || "");
  let words = String(spoken || "").replace(/\s+/g, " ").trim();
  if (!words) return before;
  const startsSentence = !before.trim() || /[.!?\n]\s*$/.test(before);
  if (startsSentence) words = words.charAt(0).toUpperCase() + words.slice(1);
  const joiner = !before || /\s$/.test(before) ? "" : " ";
  return (before + joiner + words).slice(0, maxLength);
}

/** A sentence for each recogniser error the technician can do something about. */
export function dictationError(code) {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access is blocked. Allow the microphone for this site in the browser's address bar, then try again.";
    case "audio-capture":
      return "No microphone found. Plug one in or check the device's sound settings.";
    case "network":
      return "Voice typing needs an internet connection. Check the connection and try again.";
    case "no-speech":
      return "Didn't hear anything — tap the mic and speak a little closer.";
    case "aborted":
      return "";
    default:
      return "Voice typing stopped. Tap the mic to try again.";
  }
}
