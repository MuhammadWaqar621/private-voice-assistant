import { afterEach, describe, expect, it, vi } from "vitest";
import { base64AudioToUrl, fetchTemplates, sendTurn, speakWithBrowserVoice } from "./api";

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

describe("fetchTemplates", () => {
  it("returns the parsed template list on success", async () => {
    const templates = [{ name: "Jazz", details: "..." }];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => templates })
    );
    await expect(fetchTemplates()).resolves.toEqual(templates);
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
    await expect(fetchTemplates()).rejects.toThrow("Groq is not configured.");
  });
});

describe("sendTurn", () => {
  it("posts a multipart form with the company profile, history, and the audio clip", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ user_text: "hi", reply_text: "hello", reply_audio_base64: "", language: "en-US" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const clip = new Blob(["audio-bytes"], { type: "audio/webm" });
    const company = { companyName: "Acme Widgets", companyDetails: "Sells widgets." };
    const result = await sendTurn(company, clip, [{ role: "user", content: "earlier" }]);

    expect(result.reply_text).toBe("hello");
    expect(result.language).toBe("en-US");
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/voice/turn");
    const form = options.body as FormData;
    expect(form.get("company_name")).toBe("Acme Widgets");
    expect(form.get("company_details")).toBe("Sells widgets.");
    expect(JSON.parse(form.get("history") as string)).toEqual([{ role: "user", content: "earlier" }]);
    expect(form.get("audio")).toBeInstanceOf(Blob);
  });
});

describe("speakWithBrowserVoice", () => {
  it("sets the utterance's language so non-English text isn't mispronounced", () => {
    // jsdom implements neither SpeechSynthesisUtterance nor
    // speechSynthesis - stub a minimal fake of each so the assertion can
    // inspect what speakWithBrowserVoice actually constructs and passes
    // to speak(), the same way base64AudioToUrl's test stubs createObjectURL.
    class FakeUtterance {
      lang = "";
      rate = 1;
      constructor(public text: string) {}
    }
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);

    const spoken: FakeUtterance[] = [];
    vi.stubGlobal("speechSynthesis", {
      cancel: vi.fn(),
      speak: vi.fn((u: FakeUtterance) => spoken.push(u)),
    });

    speakWithBrowserVoice("Yeh Urdu jawab hai.", "ur-PK");

    expect(spoken).toHaveLength(1);
    expect(spoken[0].lang).toBe("ur-PK");
    expect(spoken[0].text).toBe("Yeh Urdu jawab hai.");
  });
});
