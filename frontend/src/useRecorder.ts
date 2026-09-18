import { useCallback, useRef, useState } from "react";

export type RecorderStatus = "idle" | "recording" | "denied";

// Groq's Whisper endpoint rejects clips shorter than ~0.01s outright, but
// anything under a few hundred ms is just an accidental tap anyway - too
// short for real speech. Filtering those out client-side skips a pointless
// round trip to the backend for a request that can only ever fail.
const MIN_RECORDING_MS = 300;

/** Push-to-talk recording: start() opens the mic and begins capturing,
 * stop() resolves with the captured clip once the recorder has flushed
 * its final chunk (MediaRecorder.onstop fires asynchronously), or null if
 * there was no real clip to send (denied mic, or held for less than
 * MIN_RECORDING_MS). */
export function useRecorder() {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const startedAtRef = useRef<number>(0);

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      startedAtRef.current = Date.now();
      setStatus("recording");
    } catch {
      setStatus("denied");
    }
  }, []);

  const stop = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        resolve(null);
        return;
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const heldMs = Date.now() - startedAtRef.current;
        streamRef.current?.getTracks().forEach((t) => t.stop());
        setStatus("idle");
        resolve(blob.size > 0 && heldMs >= MIN_RECORDING_MS ? blob : null);
      };
      recorder.stop();
    });
  }, []);

  return { status, start, stop };
}
