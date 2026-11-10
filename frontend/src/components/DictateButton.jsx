import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

import { C, F } from "../lib/theme";
import { DICTATION_LANGUAGES, appendDictation, dictationError, recognizerClass } from "../lib/dictation";

const LANG_KEY = "crm.dictation.lang";

function savedLang() {
  try {
    return localStorage.getItem(LANG_KEY) || "en-IN";
  } catch {
    return "en-IN";
  }
}

/*
 * Voice typing for a text box: tap the mic, speak, and the words are added
 * to what's already written (the technician can still correct them before
 * saving). Uses the browser's own speech recognition -- Chrome or Edge, on
 * a phone or a computer, over https. Where that isn't available the button
 * says so instead of doing nothing.
 *
 *   <DictateButton value={note} onChange={setNote} maxLength={2000} />
 */
export default function DictateButton({ value, onChange, maxLength, label = "Speak" }) {
  const Recognizer = recognizerClass();
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const [lang, setLang] = useState(savedLang);
  const recognizer = useRef(null);
  const latest = useRef(value);  // the text as of the last change, so words land after anything typed meanwhile

  useEffect(() => { latest.current = value; }, [value]);
  useEffect(() => () => recognizer.current?.abort?.(), []);

  const chooseLang = (code) => {
    setLang(code);
    try { localStorage.setItem(LANG_KEY, code); } catch { /* per-device convenience only */ }
  };

  const start = () => {
    if (!Recognizer) return;
    setError(""); setInterim("");
    const r = new Recognizer();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) {
          const next = appendDictation(latest.current, result[0].transcript, maxLength);
          latest.current = next;
          onChange(next);
        } else {
          pending += result[0].transcript;
        }
      }
      setInterim(pending);
    };
    r.onerror = (event) => setError(dictationError(event.error));
    r.onend = () => { setListening(false); setInterim(""); recognizer.current = null; };
    recognizer.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setError(dictationError(""));
    }
  };
  const stop = () => recognizer.current?.stop();

  if (!Recognizer) {
    return (
      <p className="mt-1 flex items-center gap-1.5 text-[11px]" style={{ color: C.inkSoft, fontFamily: F.body }}>
        <Mic size={12} /> Voice typing works in Chrome or Edge (on a phone or computer).
      </p>
    );
  }

  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={listening ? stop : start} aria-pressed={listening}
          className="flex min-h-[36px] items-center gap-1.5 rounded-full px-3 py-1.5 text-xs"
          style={{
            fontFamily: F.body, fontWeight: 700,
            color: listening ? C.onAccent : C.stamp,
            backgroundColor: listening ? C.carbon : "transparent",
            border: `1px solid ${listening ? C.carbon : C.stamp}`,
          }}>
          {listening ? <><Square size={12} /> Stop</> : <><Mic size={13} /> {label}</>}
        </button>
        {listening && <span className="dictate-pulse inline-block h-2 w-2 rounded-full" style={{ backgroundColor: C.carbon }} aria-hidden />}
        <span className="text-[11px]" style={{ color: C.inkSoft, fontFamily: F.body }}>{listening ? "Listening… speak now" : "Language"}</span>
        {!listening && DICTATION_LANGUAGES.map((l) => (
          <button key={l.code} type="button" onClick={() => chooseLang(l.code)} aria-pressed={lang === l.code}
            className="rounded-full px-2 py-0.5 text-[11px]"
            style={{ fontFamily: F.body, color: lang === l.code ? C.onAccent : C.inkSoft, backgroundColor: lang === l.code ? C.stamp : "transparent", border: `1px solid ${lang === l.code ? C.stamp : C.rule}` }}>
            {l.label}
          </button>
        ))}
      </div>
      {interim && <p className="mt-1 text-xs italic" style={{ color: C.inkSoft, fontFamily: F.body }}>{interim}</p>}
      {error && <p role="alert" className="mt-1 text-[11px]" style={{ color: C.carbon, fontFamily: F.body }}>{error}</p>}
    </div>
  );
}
