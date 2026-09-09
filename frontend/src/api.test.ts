import { afterEach, describe, expect, it, vi } from "vitest";
import { base64AudioToUrl, fetchPersonas, sendTurn } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("base64AudioToUrl", () => {
  it("returns null for an empty string (server had no audio)", () => {
    expect(base64AudioToUrl("")).toBeNull();
  });

  it("produces a blob: object URL for non-empty base64 audio", () => {
    // jsdom doesn't implement createObjectURL - stub it to verify
    // base64AudioToUrl calls it with a real Blob, not the browser's
    // actual URL scheme.
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:stubbed-url") });
    const url = base64AudioToUrl(btoa("fake-mp3-bytes"));
    expect(url).toBe("blob:stubbed-url");
  });
});

describe("fetchPersonas", () => {
  it("returns the parsed persona list on success", async () => {
    const personas = [{ id: "jazz", name: "Jazz", description: "d", greeting: "g" }];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => personas })
    );
    await expect(fetchPersonas()).resolves.toEqual(personas);
  });

  it("throws the server-provided error message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: { message: "Groq is not configured." } }),
      })
    );
    await expect(fetchPersonas()).rejects.toThrow("Groq is not configured.");
  });
});

describe("sendTurn", () => {
  it("posts a multipart form with persona, history, and the audio clip", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ user_text: "hi", reply_text: "hello", reply_audio_base64: "" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const clip = new Blob(["audio-bytes"], { type: "audio/webm" });
    const result = await sendTurn("jazz", clip, [{ role: "user", content: "earlier" }]);

    expect(result.reply_text).toBe("hello");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/voice/turn");
    const form = options.body as FormData;
    expect(form.get("persona")).toBe("jazz");
    expect(JSON.parse(form.get("history") as string)).toEqual([{ role: "user", content: "earlier" }]);
    expect(form.get("audio")).toBeInstanceOf(Blob);
  });
});
