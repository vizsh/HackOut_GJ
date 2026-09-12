import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useFactoryStore } from "../../store/useFactoryStore";
import { useChatStore } from "../../store/useChatStore";
import { useTranslation } from "../../store/useLanguageStore";
import { useRoleStore } from "../../store/useRoleStore";
import { api } from "../../lib/api";

// Real tool-calling explainer (ml/explainer.py, Ollama llama3.1:8b + a
// deterministic fallback), not the keyword-regex bot this used to be. Every
// number it states traces to a real database query — see backend/app/routers/
// explainer.py and ml/explainer.py's "verified_data" guardrail for why the
// prose alone isn't trusted for numbers, and why a bad/empty tool result
// gets an honest "I don't have that" instead of a guess.

type Recognition = { continuous: boolean; interimResults: boolean; lang: string; start: () => void; stop: () => void; onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null };
type RecognitionCtor = new () => Recognition;

// Renders the explainer's markdown (tables for factory comparisons, bold
// numbers, bullet lists) instead of a wall of unformatted text — every
// number in it still traces to a real tool call (ml/explainer.py), this
// only changes how it's displayed. User messages stay plain text.
function AssistantMarkdown({ text }: { text: string }) {
  return (
    <div className="jarvis-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

const SAMPLE_PROMPTS = [
  "Which factory is performing the best?",
  "What problem does this factory have?",
  "What's the best strategy under a 10 lakh budget?",
];

export default function JarvisAssistant() {
  const factory = useFactoryStore((s) => s.baseline);
  const { lang, t } = useTranslation();
  const organizationId = useRoleStore((s) => s.organizationId);
  const [open, setOpen] = useState(false);
  const [listening, setListening] = useState(false);
  const [voice, setVoice] = useState(false);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const messages = useChatStore((s) => s.messages);
  const setMessages = useChatStore((s) => s.setMessages);
  const recognition = useRef<Recognition | null>(null);

  const speechLang = lang === "gu" ? "gu-IN" : lang === "hi" ? "hi-IN" : "en-IN";

  const speak = (text: string) => {
    if (voice && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = speechLang;
      window.speechSynthesis.speak(u);
    }
  };

  const ask = async (query: string) => {
    const clean = query.trim();
    if (!clean || thinking) return;
    setDraft("");
    setThinking(true);
    api.trackUsage("chat_question", organizationId).catch(() => {});

    let targetIndex = -1;
    setMessages((all) => {
      targetIndex = all.length + 1; // the assistant placeholder, right after the user message
      return [...all, { role: "user", text: clean }, { role: "assistant", text: "" }];
    });

    let full = "";
    try {
      await api.askStream(clean, factory.id || null, (event) => {
        if (event.type === "token") {
          full += event.text;
          const snapshot = full;
          setMessages((all) => all.map((m, i) => (i === targetIndex ? { ...m, text: snapshot } : m)));
        } else {
          setMessages((all) => all.map((m, i) => (i === targetIndex
            ? { ...m, text: event.answer, verifiedData: event.verified_data, source: event.source }
            : m)));
          speak(event.answer);
        }
      });
    } catch (err) {
      const text = `Could not reach the explainer API — is the backend running? (${err instanceof Error ? err.message : String(err)})`;
      setMessages((all) => all.map((m, i) => (i === targetIndex ? { ...m, text } : m)));
    } finally {
      setThinking(false);
    }
  };

  const startVoice = () => {
    const ctor = (window as Window & { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }).SpeechRecognition ?? (window as Window & { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition;
    if (!ctor) {
      setMessages((all) => [...all, { role: "assistant", text: "Voice input is not available in this browser. You can still type any question below." }]);
      return;
    }
    const rec = new ctor();
    rec.lang = speechLang;
    rec.continuous = false;
    rec.interimResults = false;
    rec.onresult = (event) => {
      const heard = event.results[0]?.[0]?.transcript ?? "";
      setListening(false);
      ask(heard);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recognition.current = rec;
    setListening(true);
    rec.start();
  };

  return (
    <div className="fixed bottom-4 right-4 z-[1000]">
      {open && (
        <section className="jarvis-panel mb-3 flex h-[560px] w-[440px] max-w-[92vw] flex-col overflow-hidden rounded-2xl border border-[#3ea6ff]/45 bg-[#0d1420]/95 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between border-b border-[color:var(--color-border)] bg-[#3ea6ff]/10 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="jarvis-orb" />
              <div>
                <div className="text-sm font-semibold">{t("jarvisTitle")}</div>
                <div className="text-[10px] text-[#92caff]">Real tool-calling AI · {factory.name || "no factory selected"}</div>
              </div>
            </div>
            <div className="flex gap-1">
              <button onClick={() => setVoice((v) => !v)} title="Toggle spoken answers" className={`rounded p-1.5 text-xs ${voice ? "text-[#3ea6ff]" : "text-[color:var(--color-muted)]"}`}>
                {voice ? "◖))" : "◖×"}
              </button>
              <button onClick={() => setOpen(false)} className="rounded p-1.5 text-[color:var(--color-muted)]">×</button>
            </div>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {messages.map((m, i) => {
              const isLive = thinking && i === messages.length - 1 && m.role === "assistant";
              return (
                <div key={i} className={`max-w-[92%] rounded-xl px-3 py-2 text-[12px] leading-relaxed ${m.role === "assistant" ? "bg-[#172335] text-[color:var(--color-text)]" : "ml-auto bg-[#3ea6ff] text-[#07101c]"}`}>
                  <div>
                    {m.role === "assistant" && m.text ? (
                      <AssistantMarkdown text={m.text} />
                    ) : (
                      m.text || (isLive ? "Calling the database…" : "")
                    )}
                    {isLive && m.text && <span className="jarvis-cursor" />}
                  </div>
                  {m.verifiedData != null && (
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-[10px] text-[#8fb8e0]">See the real numbers</summary>
                      <pre className="mt-1 max-h-40 overflow-auto rounded bg-black/30 p-1.5 text-[9.5px] leading-snug text-[#b9dcff]">
                        {JSON.stringify(m.verifiedData, null, 1)}
                      </pre>
                    </details>
                  )}
                  {m.source && (
                    <div className="mt-1 text-[9px] uppercase tracking-wide text-[#5f7c99]">{m.source}</div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="border-t border-[color:var(--color-border)] p-3">
            <div className="mb-2 flex flex-wrap gap-1">
              {SAMPLE_PROMPTS.map((prompt) => (
                <button key={prompt} onClick={() => ask(prompt)} className="rounded-full border border-[color:var(--color-border)] px-2 py-1 text-[10px] text-[color:var(--color-muted)] hover:border-[#3ea6ff]/60 hover:text-[#b9dcff]">
                  {prompt}
                </button>
              ))}
            </div>
            <form onSubmit={(e) => { e.preventDefault(); ask(draft); }} className="flex gap-2">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={t("jarvisAskPlaceholder")}
                disabled={thinking}
                className="min-w-0 flex-1 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] px-3 py-2 text-xs outline-none focus:border-[#3ea6ff] disabled:opacity-50"
              />
              <button
                type="button"
                onClick={startVoice}
                disabled={thinking}
                className={`rounded-lg border px-2.5 text-xs ${listening ? "border-[color:var(--color-crit)] bg-[color:var(--color-crit)]/15 text-[color:var(--color-crit)]" : "border-[color:var(--color-border)] text-[#9fd3ff]"}`}
              >
                {listening ? "●" : "◉"}
              </button>
              <button disabled={thinking} className="rounded-lg bg-[#3ea6ff] px-3 text-xs font-bold text-[#07101c] disabled:opacity-50">↑</button>
            </form>
          </div>
        </section>
      )}
      <button
        onClick={() => setOpen((x) => !x)}
        className="flex items-center gap-2 rounded-full border border-[#3ea6ff]/60 bg-[#101b2b] px-4 py-3 text-sm font-semibold text-[#d9ecff] shadow-lg shadow-[#3ea6ff]/15 hover:bg-[#16283f]"
      >
        <span className="jarvis-orb" /> {t("jarvisButton")}
      </button>
    </div>
  );
}
