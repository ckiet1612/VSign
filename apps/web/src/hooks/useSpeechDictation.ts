import { useCallback, useEffect, useRef, useState } from "react";

// The Web Speech API is not in the TypeScript DOM library yet; only the parts used here are typed.
interface RecognitionResult { readonly isFinal: boolean; readonly 0: { readonly transcript: string } }
interface RecognitionEvent { readonly resultIndex: number; readonly results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string; interimResults: boolean; continuous: boolean; maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const scope = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Trình duyệt chưa cho dùng micro. Hãy cấp quyền micro cho trang này.",
  "service-not-allowed": "Trình duyệt không cho dùng dịch vụ nhận dạng giọng nói.",
  "no-speech": "Chưa nghe thấy giọng nói. Hãy bấm micro và nói lại.",
  "audio-capture": "Không tìm thấy micro.",
  network: "Không kết nối được dịch vụ nhận dạng giọng nói của trình duyệt.",
  "language-not-supported": "Trình duyệt chưa hỗ trợ nhận dạng tiếng Việt.",
};

export type DictationStatus = "unsupported" | "idle" | "listening";

/**
 * Speech to text for the staff reply, through the browser's own recognizer (Vietnamese). It runs only between
 * a press on the microphone and the end of the utterance; VSign never receives or stores the audio.
 */
export function useSpeechDictation(onText: (text: string, final: boolean) => void) {
  const [status, setStatus] = useState<DictationStatus>(() => recognitionConstructor() ? "idle" : "unsupported");
  const [error, setError] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const handler = useRef(onText);
  handler.current = onText;

  const stop = useCallback(() => { recognition.current?.stop(); }, []);
  const start = useCallback(() => {
    const Constructor = recognitionConstructor();
    if (!Constructor || recognition.current) return;
    const instance = new Constructor();
    instance.lang = "vi-VN";
    instance.interimResults = true;
    instance.continuous = false;
    instance.maxAlternatives = 1;
    instance.onresult = event => {
      let text = "", final = false;
      for (let index = 0; index < event.results.length; index += 1) {
        text += event.results[index][0].transcript;
        final = event.results[index].isFinal;
      }
      handler.current(text.trim(), final);
    };
    instance.onerror = event => { if (event.error !== "aborted") setError(ERRORS[event.error] ?? "Chưa nhận dạng được giọng nói."); };
    instance.onend = () => { if (recognition.current === instance) recognition.current = null; setStatus("idle"); };
    recognition.current = instance;
    setError("");
    try {
      instance.start();
      setStatus("listening");
    } catch {
      recognition.current = null;
      setError("Chưa bật được micro. Hãy thử lại.");
    }
  }, []);

  useEffect(() => () => { recognition.current?.abort(); recognition.current = null; }, []);
  return { status, error, start, stop };
}
