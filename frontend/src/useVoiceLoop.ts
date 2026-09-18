import { useCallback, useRef, useState } from "react";

export type ListenStatus = "idle" | "listening" | "denied";

// Root-mean-square amplitude (0-1 scale) below which the mic is considered
// silent. Tuned for a normal-volume voice in a quiet-ish room; a noisy
// environment may need this raised.
const SILENCE_THRESHOLD = 0.02;
// How long the mic has to stay below SILENCE_THRESHOLD, after speech was
// heard, before a turn is considered over and gets sent.
const SILENCE_DURATION_MS = 1000;
// Minimum time speech must have been present before silence can end the
// turn - guards against a single short noise spike triggering an instant cut.
const MIN_SPEECH_MS = 300;
// Hard cap per turn so one held-open mic (e.g. a noisy room that never goes
// quiet) can't record forever.
const MAX_RECORDING_MS = 20000;

export interface ListenResult {
  blob: Blob | null; // null when nothing usable was captured
  denied: boolean; // true when getUserMedia itself failed/was refused
}

/** Hands-free listening: listen() opens the mic, records continuously, and
 * auto-detects when the caller has stopped talking (via volume analysis)
 * instead of waiting for an explicit stop() call. Resolves with the clip
 * once silence is detected, or a null blob if the mic was denied or
 * nothing was said before MAX_RECORDING_MS elapsed - `denied` tells the
 * caller which of those two happened. cancel() aborts a call in progress
 * (e.g. the user pressed "End Call" mid-turn). */
export function useVoiceLoop() {
  const [status, setStatus] = useState<ListenStatus>("idle");
  const resolveRef = useRef<((result: ListenResult) => void) | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (audioCtxRef.current) void audioCtxRef.current.close().catch(() => {});
    audioCtxRef.current = null;
    mediaRecorderRef.current = null;
  }, []);

  const listen = useCallback((): Promise<ListenResult> => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;

      navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then((stream) => {
          if (resolveRef.current !== resolve) {
            // cancel() already ran while permission was pending
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          streamRef.current = stream;

          const audioCtx = new AudioContext();
          audioCtxRef.current = audioCtx;
          const source = audioCtx.createMediaStreamSource(stream);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 512;
          source.connect(analyser);
          const data = new Uint8Array(analyser.fftSize);

          const recorder = new MediaRecorder(stream);
          mediaRecorderRef.current = recorder;
          chunksRef.current = [];
          recorder.ondataavailable = (e) => {
            if (e.data.size > 0) chunksRef.current.push(e.data);
          };

          const finish = (send: boolean) => {
            if (!resolveRef.current) return;
            const resolveFn = resolveRef.current;
            resolveRef.current = null;
            recorder.onstop = () => {
              const blob = send ? new Blob(chunksRef.current, { type: "audio/webm" }) : null;
              cleanup();
              setStatus("idle");
              resolveFn({ blob: blob && blob.size > 0 ? blob : null, denied: false });
            };
            if (recorder.state !== "inactive") recorder.stop();
            else {
              cleanup();
              setStatus("idle");
              resolveFn({ blob: null, denied: false });
            }
          };

          recorder.start();
          setStatus("listening");

          const startedAt = Date.now();
          let hasSpoken = false;
          let silenceStartedAt: number | null = null;

          const tick = () => {
            analyser.getByteTimeDomainData(data);
            let sumSquares = 0;
            for (let i = 0; i < data.length; i++) {
              const v = (data[i] - 128) / 128;
              sumSquares += v * v;
            }
            const rms = Math.sqrt(sumSquares / data.length);
            const now = Date.now();

            if (rms > SILENCE_THRESHOLD) {
              hasSpoken = true;
              silenceStartedAt = null;
            } else if (hasSpoken) {
              if (silenceStartedAt == null) silenceStartedAt = now;
              else if (
                now - silenceStartedAt >= SILENCE_DURATION_MS &&
                now - startedAt >= MIN_SPEECH_MS
              ) {
                finish(true);
                return;
              }
            }

            if (now - startedAt >= MAX_RECORDING_MS) {
              finish(hasSpoken);
              return;
            }

            rafRef.current = requestAnimationFrame(tick);
          };
          rafRef.current = requestAnimationFrame(tick);
        })
        .catch(() => {
          if (resolveRef.current !== resolve) return;
          resolveRef.current = null;
          setStatus("denied");
          resolve({ blob: null, denied: true });
        });
    });
  }, [cleanup]);

  const cancel = useCallback(() => {
    const resolveFn = resolveRef.current;
    resolveRef.current = null;
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        // already stopped/inactive - nothing to do
      }
    }
    cleanup();
    setStatus("idle");
    resolveFn?.({ blob: null, denied: false });
  }, [cleanup]);

  return { status, listen, cancel };
}
