import { useEffect, useRef, useState } from "react";
import {
  base64AudioToUrl,
  fetchGreeting,
  fetchTemplates,
  sendTurn,
  speakWithBrowserVoice,
  type ChatTurn,
  type CompanyProfile,
  type ExampleTemplate,
} from "./api";
import { useVoiceLoop } from "./useVoiceLoop";

type Stage = "setup" | "idle" | "connecting" | "connected" | "ended";
// What the hands-free loop is doing right now, only meaningful while
// stage === "connected". null means the loop isn't running (call just
// started, or just ended).
type TurnPhase = "listening" | "thinking" | "speaking" | null;

const STORAGE_KEY = "private-voice-assistant.company-profile";

function loadSavedProfile(): CompanyProfile {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as CompanyProfile;
  } catch {
    // corrupt/blocked storage - fall through to a blank profile
  }
  return { companyName: "", companyDetails: "" };
}

// How long a toast stays on screen before it auto-dismisses itself.
const TOAST_MS = 4000;

export default function App() {
  const [templates, setTemplates] = useState<ExampleTemplate[]>([]);
  const [companyName, setCompanyName] = useState("");
  const [companyDetails, setCompanyDetails] = useState("");
  const [stage, setStage] = useState<Stage>("setup");
  const [turnPhase, setTurnPhase] = useState<TurnPhase>(null);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Mirrors `history` so the loop always sends the latest transcript even
  // though it started running (and closed over `history`) turns ago.
  const historyRef = useRef<ChatTurn[]>([]);
  // Whether the hands-free listen/reply loop should keep going. A ref
  // (not state) because handleEndCall must stop the loop on its very next
  // check, not after a re-render.
  const activeRef = useRef(false);
  const { status: micStatus, listen, cancel } = useVoiceLoop();

  function showToast(message: string) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = setTimeout(() => setToast(null), TOAST_MS);
  }

  function pushHistory(turns: ChatTurn[]) {
    historyRef.current = turns;
    setHistory(turns);
  }

  useEffect(() => {
    const saved = loadSavedProfile();
    setCompanyName(saved.companyName);
    setCompanyDetails(saved.companyDetails);
    fetchTemplates()
      .then(setTemplates)
      .catch(() => {
        /* quick-fill templates are a convenience, not required - a failed
         * fetch just means an empty template list, the form still works */
      });
  }, []);

  function applyTemplate(template: ExampleTemplate) {
    setCompanyName(template.name);
    setCompanyDetails(template.details);
  }

  function startSetup() {
    const profile: CompanyProfile = { companyName, companyDetails };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
    } catch {
      // best-effort persistence only
    }
    setStage("idle");
  }

  /** Plays the reply (server audio if we have it, else the browser's own
   * voice) and resolves once it's actually finished playing - the loop
   * awaits this so it doesn't start listening again while the assistant
   * is still talking (which would otherwise just re-transcribe itself). */
  function playReply(audioBase64: string, text: string, lang: string): Promise<void> {
    const url = base64AudioToUrl(audioBase64);
    if (url && audioRef.current) {
      const audio = audioRef.current;
      audio.src = url;
      return new Promise((resolve) => {
        const onEnded = () => {
          audio.removeEventListener("ended", onEnded);
          resolve();
        };
        audio.addEventListener("ended", onEnded);
        void audio.play().catch(() => {
          audio.removeEventListener("ended", onEnded);
          resolve();
        });
      });
    }
    return speakWithBrowserVoice(text, lang);
  }

  /** The hands-free call loop: listen for a turn, send it, play the
   * reply, repeat - until activeRef.current goes false (End Call) or the
   * mic gets denied. */
  async function runCallLoop(company: CompanyProfile) {
    while (activeRef.current) {
      setTurnPhase("listening");
      const { blob, denied } = await listen();
      if (!activeRef.current) break;

      if (denied) {
        showToast("Microphone access was denied - allow it in your browser to talk.");
        break;
      }
      if (!blob) {
        showToast("Didn't catch anything - try again.");
        continue;
      }

      setTurnPhase("thinking");
      try {
        const result = await sendTurn(company, blob, historyRef.current);
        pushHistory([
          ...historyRef.current,
          { role: "user", content: result.user_text },
          { role: "assistant", content: result.reply_text },
        ]);
        if (!activeRef.current) break;
        setTurnPhase("speaking");
        await playReply(result.reply_audio_base64, result.reply_text, result.language);
      } catch (e) {
        showToast((e as Error).message);
      }
    }
    setTurnPhase(null);
  }

  async function handleCall() {
    pushHistory([]);
    setStage("connecting");
    const company: CompanyProfile = { companyName, companyDetails };
    try {
      const greeting = await fetchGreeting(company);
      pushHistory([{ role: "assistant", content: greeting.greeting_text }]);
      setStage("connected");
      activeRef.current = true;
      await playReply(greeting.greeting_audio_base64, greeting.greeting_text, greeting.language);
      if (activeRef.current) void runCallLoop(company);
    } catch (e) {
      showToast((e as Error).message);
      setStage("idle");
    }
  }

  function handleEndCall() {
    activeRef.current = false;
    cancel();
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
    setTurnPhase(null);
    setStage("ended");
  }

  if (stage === "setup") {
    return (
      <div className="phone">
        <header>
          <h1>Private Voice Assistant</h1>
          <p className="subtitle">Set up an AI helpline for any company</p>
        </header>

        {templates.length > 0 && (
          <div className="templates">
            <span className="templates-label">Quick-fill an example:</span>
            <div className="template-buttons">
              {templates.map((t) => (
                <button key={t.name} className="btn template" onClick={() => applyTemplate(t)}>
                  {t.name}
                </button>
              ))}
            </div>
          </div>
        )}

        <form
          className="setup-form"
          onSubmit={(e) => {
            e.preventDefault();
            startSetup();
          }}
        >
          <label htmlFor="company-name">Company name</label>
          <input
            id="company-name"
            type="text"
            placeholder="e.g. Acme Widgets"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            required
          />

          <label htmlFor="company-details">
            Tell the assistant about your company (services, policies, common questions, contact
            info…)
          </label>
          <textarea
            id="company-details"
            rows={8}
            placeholder="e.g. Acme Widgets sells industrial widgets. Standard delivery takes 3-5 business days. Returns accepted within 30 days with a receipt. Support line: 555-0100."
            value={companyDetails}
            onChange={(e) => setCompanyDetails(e.target.value)}
          />

          <button type="submit" className="btn call" disabled={!companyName.trim()}>
            Continue →
          </button>
        </form>
      </div>
    );
  }

  const statusLabel =
    stage === "connecting"
      ? "Connecting…"
      : turnPhase === "listening"
        ? "🎙 Listening…"
        : turnPhase === "thinking"
          ? "Thinking…"
          : turnPhase === "speaking"
            ? "🔊 Speaking…"
            : null;

  return (
    <div className="phone">
      <header>
        <h1>Private Voice Assistant</h1>
        <p className="subtitle">Calling: {companyName}</p>
      </header>

      {micStatus === "denied" && (
        <div className="banner error">Microphone access was denied - allow it in your browser to talk.</div>
      )}

      <div className="call-controls">
        {stage === "idle" || stage === "ended" ? (
          <>
            <button className="btn call" onClick={handleCall}>
              📞 Call
            </button>
            <button className="btn link" onClick={() => setStage("setup")}>
              ← Change company
            </button>
          </>
        ) : (
          <button className="btn end" onClick={handleEndCall}>
            ☎ End Call
          </button>
        )}

        {statusLabel && (
          <p className={`call-status ${turnPhase === "listening" ? "listening" : ""}`}>{statusLabel}</p>
        )}
      </div>

      <div className="transcript" aria-live="polite">
        {history.map((turn, i) => (
          <div key={i} className={`bubble ${turn.role}`}>
            <span className="role">{turn.role === "user" ? "You" : "Assistant"}</span>
            <p>{turn.content}</p>
          </div>
        ))}
        {stage === "idle" && history.length === 0 && (
          <p className="hint">Press "Call" to start.</p>
        )}
      </div>

      <audio ref={audioRef} hidden />
      {toast && (
        <div className="toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
    </div>
  );
}
