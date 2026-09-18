export interface CompanyProfile {
  companyName: string;
  companyDetails: string;
}

export interface ExampleTemplate {
  name: string;
  details: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface TurnResult {
  user_text: string;
  reply_text: string;
  reply_audio_base64: string;
  language: string; // BCP-47 tag (e.g. "ur-PK") for the browser-voice fallback
}

export interface GreetingResult {
  greeting_text: string;
  greeting_audio_base64: string;
  language: string;
}

// In production the backend is served from the same Vercel deployment (see
// vercel.json's /api rewrite), so relative paths just work; only local dev
// needs an absolute URL to reach the separately-running backend on :8010.
const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.PROD ? "" : "http://localhost:8010");

async function parseErrorDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message as string;
  } catch {
    // response wasn't JSON - fall through to the generic message below
  }
  return `Request failed (${resp.status})`;
}

/** Optional quick-fill starting points for the setup form - any company
 * name/details a visitor types in works just as well; these just save a
 * first-time visitor from starting on a blank form. */
export async function fetchTemplates(): Promise<ExampleTemplate[]> {
  const resp = await fetch(`${BASE_URL}/api/voice/templates`);
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

export async function fetchGreeting(company: CompanyProfile): Promise<GreetingResult> {
  const params = new URLSearchParams({
    company_name: company.companyName,
    company_details: company.companyDetails,
  });
  const resp = await fetch(`${BASE_URL}/api/voice/greeting?${params}`);
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

export async function sendTurn(
  company: CompanyProfile,
  audio: Blob,
  history: ChatTurn[]
): Promise<TurnResult> {
  const form = new FormData();
  form.append("company_name", company.companyName);
  form.append("company_details", company.companyDetails);
  form.append("history", JSON.stringify(history));
  form.append("audio", audio, "clip.webm");

  const resp = await fetch(`${BASE_URL}/api/voice/turn`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

/** Decodes a base64 WAV clip (Groq's Orpheus TTS only supports wav output)
 * into a playable object URL, or null when the server had no audio
 * (caller falls back to speakWithBrowserVoice). */
export function base64AudioToUrl(base64: string): string | null {
  if (!base64) return null;
  const bytes = atob(base64);
  const buffer = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
  const blob = new Blob([buffer], { type: "audio/wav" });
  return URL.createObjectURL(blob);
}

/** speechSynthesis.getVoices() can return [] on the very first call -
 * voice lists load asynchronously and the 'voiceschanged' event fires
 * once they're ready. Waits for that (capped at 300ms - some browsers
 * never fire it when there genuinely are no voices, so this can't wait
 * forever). */
function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    const existing = window.speechSynthesis.getVoices();
    if (existing.length > 0) {
      resolve(existing);
      return;
    }
    const onChange = () => {
      window.speechSynthesis.removeEventListener("voiceschanged", onChange);
      clearTimeout(timer);
      resolve(window.speechSynthesis.getVoices());
    };
    const timer = setTimeout(() => {
      window.speechSynthesis.removeEventListener("voiceschanged", onChange);
      resolve(window.speechSynthesis.getVoices());
    }, 300);
    window.speechSynthesis.addEventListener("voiceschanged", onChange);
  });
}

/** Urdu voices are rare on desktop browsers/OSes - many installs have no
 * "ur" voice at all, and some browsers (Chrome on Windows in particular)
 * silently produce no audio at all for a `lang` with zero matching
 * voices, rather than falling back to a default one. Picks the closest
 * available voice instead of leaving that to the browser: an exact
 * match, then same base language (e.g. any "ur-*"), then - specifically
 * for Urdu - a Hindi voice as the nearest phonetic substitute (the two
 * languages sound alike, so it's still intelligible), then whatever
 * default voice the system has as a last resort. */
function pickVoice(voices: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  if (voices.length === 0) return null;
  const lower = lang.toLowerCase();
  const base = lower.split("-")[0];
  return (
    voices.find((v) => v.lang.toLowerCase() === lower) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(base)) ??
    (base === "ur" ? voices.find((v) => v.lang.toLowerCase().startsWith("hi")) : undefined) ??
    voices.find((v) => v.default) ??
    voices[0]
  );
}

/** Fallback voice for whenever the server sends no audio - either Groq TTS
 * isn't available (see backend README: Orpheus requires one-time terms
 * acceptance in the Groq console), or the reply is in a language Orpheus
 * doesn't support (it's English-only; the backend only attempts Groq TTS
 * for English replies - see backend/app/api/voice.py's _try_synthesize).
 * `lang` (a BCP-47 tag from the API response) picks a matching voice/
 * pronunciation so a non-English reply isn't read with an English accent
 * or skipped by browsers that need an exact voice match. Resolves once
 * speech finishes (or immediately if speech synthesis isn't available at
 * all), so callers running a hands-free listen/speak loop know when it's
 * safe to start listening for the caller's next turn. */
export async function speakWithBrowserVoice(text: string, lang: string): Promise<void> {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 1.0;
  const voice = pickVoice(await loadVoices(), lang);
  if (voice) utterance.voice = voice;
  return new Promise((resolve) => {
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  });
}
