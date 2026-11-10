import test from "node:test";
import assert from "node:assert/strict";
import { appendDictation, dictationError, recognizerClass } from "./dictation.js";

test("spoken words join what's typed with one space and a capital at a sentence start", () => {
  assert.equal(appendDictation("", "screen flickering"), "Screen flickering");
  assert.equal(appendDictation("Screen flickering.", "hinge broken"), "Screen flickering. Hinge broken");
  assert.equal(appendDictation("Screen", "  flickers   on boot "), "Screen flickers on boot");
  assert.equal(appendDictation("Line one\n", "next"), "Line one\nNext");
  assert.equal(appendDictation("abc", ""), "abc");
});

test("never longer than the field allows", () => {
  assert.equal(appendDictation("12345", "678910", 8), "12345 67");
});

test("recogniser detection and error messages", () => {
  assert.equal(recognizerClass({}), null);
  const Fake = function () {};
  assert.equal(recognizerClass({ webkitSpeechRecognition: Fake }), Fake);
  assert.match(dictationError("not-allowed"), /Microphone access is blocked/);
  assert.equal(dictationError("aborted"), "");
});
