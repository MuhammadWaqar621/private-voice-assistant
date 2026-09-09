export interface Persona {
  id: string;
  name: string;
  description: string;
  greeting: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface TurnResult {
  user_text: string;
  reply_text: string;
  reply_audio_base64: string;
}

export interface GreetingResult {
  greeting_text: string;
  greeting_audio_base64: string;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

export async function fetchPersonas(): Promise<Persona[]> {
  const resp = await fetch(`${BASE_URL}/api/voice/personas`);
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

export async function fetchGreeting(personaId: string): Promise<GreetingResult> {
  const resp = await fetch(`${BASE_URL}/api/voice/greeting/${personaId}`);
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

export async function sendTurn(
  personaId: string,
  audio: Blob,
  history: ChatTurn[]
): Promise<TurnResult> {
  const form = new FormData();
  form.append("persona", personaId);
  form.append("history", JSON.stringify(history));
  form.append("audio", audio, "clip.webm");

  const resp = await fetch(`${BASE_URL}/api/voice/turn`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(await parseErrorDetail(resp));
  return resp.json();
}

/** Decodes a base64 mp3/wav clip into a playable object URL, or null when
 * the server had no audio (caller falls back to speakWithBrowserVoice). */
export function base64AudioToUrl(base64: string): string | null {
  if (!base64) return null;
  const bytes = atob(base64);
  const buffer = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
  const blob = new Blob([buffer], { type: "audio/mpeg" });
  return URL.createObjectURL(blob);
}

/** Fallback voice when Groq TTS isn't available server-side (see backend
 * README: Orpheus requires one-time terms acceptance in the Groq console).
 * Every modern desktop browser ships a speechSynthesis voice, so the call
 * still "speaks" without any extra setup. */
export function speakWithBrowserVoice(text: string): void {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.0;
  window.speechSynthesis.speak(utterance);
}
