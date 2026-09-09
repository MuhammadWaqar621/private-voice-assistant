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

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010";

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

/** Fallback voice for whenever the server sends no audio - either Groq TTS
 * isn't available (see backend README: Orpheus requires one-time terms
 * acceptance in the Groq console), or the reply is in a language Orpheus
 * doesn't support (it's English-only; the backend only attempts Groq TTS
 * for English replies - see backend/app/api/voice.py's _try_synthesize).
 * `lang` (a BCP-47 tag from the API response) picks a matching voice/
 * pronunciation so a non-English reply isn't read with an English accent
 * or skipped by browsers that need an exact voice match. */
export function speakWithBrowserVoice(text: string, lang: string): void {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 1.0;
  window.speechSynthesis.speak(utterance);
}
