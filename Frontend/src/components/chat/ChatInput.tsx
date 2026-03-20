"use client";
import { useState, useRef, KeyboardEvent } from "react";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { Send, Mic, MicOff, Loader2 } from "lucide-react";
import clsx from "clsx";

interface Props { onSend:(t:string)=>void; loading:boolean; hasDocs:boolean; }

export default function ChatInput({ onSend, loading, hasDocs }: Props) {
  const [val, setVal] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Voice input: khi nhận được kết quả cuối cùng → điền vào ô input
  const { listening, supported, interim, start, stop } = useVoiceInput(
    (final) => setVal(p => (p ? p + " " + final : final).trim())
  );

  const resize = () => {
    if (!ref.current) return;
    ref.current.style.height = "auto";
    ref.current.style.height = Math.min(ref.current.scrollHeight, 160) + "px";
  };

  const send = () => {
    const text = val.trim();
    if (!text || loading) return;
    onSend(text); setVal("");
    if (ref.current) ref.current.style.height = "auto";
  };

  const display = listening && interim ? val + (val ? " " : "") + interim : val;

  return (
    <div className="space-y-2">
      {/* Indicator đang nghe */}
      {listening && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-accent/5 border border-accent/20 rounded-xl animate-fade-up">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75"/>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-accent"/>
          </span>
          <span className="text-xs text-accent">Đang nghe tiếng Việt...</span>
          {interim && <span className="text-xs text-text-muted italic truncate max-w-[200px]">"{interim}"</span>}
        </div>
      )}

      {/* Input box */}
      <div className={clsx(
        "flex items-end gap-2 px-3 py-2 rounded-2xl border transition-all duration-200",
        listening
          ? "border-accent/50 bg-accent/5"
          : "border-surface-3 bg-surface-1 focus-within:border-accent/40"
      )}>
        <textarea ref={ref} value={display}
          onChange={e => { setVal(e.target.value); resize(); }}
          onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          placeholder={
            listening ? "Đang nhận giọng nói..."
            : hasDocs  ? "Hỏi về tài liệu đã ingest hoặc bất kỳ điều gì..."
            :            "Hỏi bất kỳ điều gì về nghiên cứu..."
          }
          disabled={loading}
          rows={1}
          className="flex-1 bg-transparent resize-none outline-none text-sm text-text-primary placeholder:text-text-muted leading-6 max-h-40 disabled:opacity-60"
        />

        {/* Nút Voice */}
        {supported && (
          <button onClick={() => listening ? stop() : start()} disabled={loading}
            title={listening ? "Dừng ghi âm" : "Nhập bằng giọng nói (tiếng Việt)"}
            className={clsx(
              "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all disabled:opacity-50",
              listening
                ? "bg-accent text-surface-DEFAULT scale-110 shadow-lg shadow-accent/25"
                : "text-text-muted hover:text-accent hover:bg-accent/10"
            )}>
            {listening ? <MicOff className="w-3.5 h-3.5"/> : <Mic className="w-3.5 h-3.5"/>}
          </button>
        )}

        {/* Nút Send */}
        <button onClick={send} disabled={!val.trim() || loading}
          className={clsx(
            "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all",
            val.trim() && !loading
              ? "bg-accent text-surface-DEFAULT hover:bg-accent-dim hover:scale-105"
              : "bg-surface-3 text-text-muted cursor-not-allowed"
          )}>
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <Send className="w-3.5 h-3.5"/>}
        </button>
      </div>

      <p className="text-xs text-center text-text-muted opacity-40">
        Enter gửi · Shift+Enter xuống dòng{supported && " · 🎤 hỗ trợ giọng nói tiếng Việt"}
      </p>
    </div>
  );
}