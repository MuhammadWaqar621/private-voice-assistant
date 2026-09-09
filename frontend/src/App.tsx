import { useEffect, useRef, useState } from "react";
import {
  base64AudioToUrl,
  fetchGreeting,
  fetchPersonas,
  sendTurn,
  speakWithBrowserVoice,
  type ChatTurn,
  type Persona,
} from "./api";
import { useRecorder } from "./useRecorder";

type CallState = "idle" | "connecting" | "connected" | "thinking" | "ended";

export default function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState<string>("");
  const [callState, setCallState] = useState<CallState>("idle");
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const { status: recStatus, start, stop } = useRecorder();

  useEffect(() => {
    fetchPersonas()
      .then((list) => {
        setPersonas(list);
        if (list.length > 0) setPersonaId(list[0].id);
      })
      .catch((e) => setError(e.message));
  }, []);

  function playOrSpeak(audioBase64: string, text: string, lang: string) {
    const url = base64AudioToUrl(audioBase64);
    if (url && audioRef.current) {
      audioRef.current.src = url;
      void audioRef.current.play();
    } else {
      speakWithBrowserVoice(text, lang);
    }
  }

  async function handleCall() {
    setError(null);
    setHistory([]);
    setCallState("connecting");
    try {
      const greeting = await fetchGreeting(personaId);
      setHistory([{ role: "assistant", content: greeting.greeting_text }]);
      playOrSpeak(greeting.greeting_audio_base64, greeting.greeting_text, greeting.language);
      setCallState("connected");
    } catch (e) {
      setError((e as Error).message);
      setCallState("idle");
    }
  }

  function handleEndCall() {
    window.speechSynthesis?.cancel();
    setCallState("ended");
  }

  async function handleMicDown() {
    if (callState !== "connected") return;
    setError(null);
    await start();
  }

  async function handleMicUp() {
    if (recStatus !== "recording") return;
    const clip = await stop();
    if (!clip) return;

    setCallState("thinking");
    try {
      const result = await sendTurn(personaId, clip, history);
      const nextHistory: ChatTurn[] = [
        ...history,
        { role: "user", content: result.user_text },
        { role: "assistant", content: result.reply_text },
      ];
      setHistory(nextHistory);
      playOrSpeak(result.reply_audio_base64, result.reply_text, result.language);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCallState("connected");
    }
  }

  const selectedPersona = personas.find((p) => p.id === personaId);
  const onCall = callState === "connected" || callState === "thinking";

  return (
    <div className="phone">
      <header>
        <h1>Private Voice Assistant</h1>
        <p className="subtitle">AI-powered call center helpline (demo)</p>
      </header>

      {error && <div className="banner error">{error}</div>}
      {recStatus === "denied" && (
        <div className="banner error">Microphone access was denied - allow it in your browser to talk.</div>
      )}

      <div className="persona-select">
        <label htmlFor="persona">Calling:</label>
        <select
          id="persona"
          value={personaId}
          disabled={onCall}
          onChange={(e) => setPersonaId(e.target.value)}
        >
          {personas.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {selectedPersona && <p className="persona-desc">{selectedPersona.description}</p>}
      </div>

      <div className="call-controls">
        {callState === "idle" || callState === "ended" ? (
          <button className="btn call" onClick={handleCall} disabled={!personaId}>
            📞 Call
          </button>
        ) : (
          <button className="btn end" onClick={handleEndCall}>
            ☎ End Call
          </button>
        )}

        {onCall && (
          <button
            className={`btn talk ${recStatus === "recording" ? "recording" : ""}`}
            disabled={callState === "thinking"}
            onMouseDown={handleMicDown}
            onMouseUp={handleMicUp}
            onMouseLeave={() => recStatus === "recording" && handleMicUp()}
            onTouchStart={(e) => {
              e.preventDefault();
              void handleMicDown();
            }}
            onTouchEnd={(e) => {
              e.preventDefault();
              void handleMicUp();
            }}
          >
            {callState === "thinking"
              ? "Thinking…"
              : recStatus === "recording"
                ? "🔴 Release to send"
                : "🎙 Hold to talk"}
          </button>
        )}
      </div>

      <div className="transcript" aria-live="polite">
        {history.map((turn, i) => (
          <div key={i} className={`bubble ${turn.role}`}>
            <span className="role">{turn.role === "user" ? "You" : "Assistant"}</span>
            <p>{turn.content}</p>
          </div>
        ))}
        {callState === "idle" && history.length === 0 && (
          <p className="hint">Choose who you're calling, then press "Call" to start.</p>
        )}
      </div>

      <audio ref={audioRef} hidden />
    </div>
  );
}
