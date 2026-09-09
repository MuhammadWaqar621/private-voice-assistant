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
import { useRecorder } from "./useRecorder";

type Stage = "setup" | "idle" | "connecting" | "connected" | "thinking" | "ended";

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

export default function App() {
  const [templates, setTemplates] = useState<ExampleTemplate[]>([]);
  const [companyName, setCompanyName] = useState("");
  const [companyDetails, setCompanyDetails] = useState("");
  const [stage, setStage] = useState<Stage>("setup");
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const { status: recStatus, start, stop } = useRecorder();

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
    setStage("connecting");
    const company: CompanyProfile = { companyName, companyDetails };
    try {
      const greeting = await fetchGreeting(company);
      setHistory([{ role: "assistant", content: greeting.greeting_text }]);
      playOrSpeak(greeting.greeting_audio_base64, greeting.greeting_text, greeting.language);
      setStage("connected");
    } catch (e) {
      setError((e as Error).message);
      setStage("idle");
    }
  }

  function handleEndCall() {
    window.speechSynthesis?.cancel();
    setStage("ended");
  }

  async function handleMicDown() {
    if (stage !== "connected") return;
    setError(null);
    await start();
  }

  async function handleMicUp() {
    if (recStatus !== "recording") return;
    const clip = await stop();
    if (!clip) return;

    setStage("thinking");
    try {
      const company: CompanyProfile = { companyName, companyDetails };
      const result = await sendTurn(company, clip, history);
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
      setStage("connected");
    }
  }

  const onCall = stage === "connected" || stage === "thinking";

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

  return (
    <div className="phone">
      <header>
        <h1>Private Voice Assistant</h1>
        <p className="subtitle">Calling: {companyName}</p>
      </header>

      {error && <div className="banner error">{error}</div>}
      {recStatus === "denied" && (
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

        {onCall && (
          <button
            className={`btn talk ${recStatus === "recording" ? "recording" : ""}`}
            disabled={stage === "thinking"}
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
            {stage === "thinking"
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
        {stage === "idle" && history.length === 0 && (
          <p className="hint">Press "Call" to start.</p>
        )}
      </div>

      <audio ref={audioRef} hidden />
    </div>
  );
}
