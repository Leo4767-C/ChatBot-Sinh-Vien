"use client";
import { useRef, useState, KeyboardEvent, ChangeEvent } from "react";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { Send, Mic, MicOff, Loader2, Image as ImageIcon, X } from "lucide-react";
import clsx from "clsx";

interface Props {
  onSend: (t: string) => void;
  onSendImage: (file: File, prompt?: string) => void;
  loading: boolean;
  hasDocs: boolean;
}

export default function ChatInput({ onSend, onSendImage, loading, hasDocs }: Props) {
  const [val, setVal] = useState("");
  const [pickedImage, setPickedImage] = useState<File | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { listening, supported, interim, start, stop } = useVoiceInput(
    (final) => setVal((p) => (p ? p + " " + final : final).trim())
  );

  const resize = () => {
    if (!ref.current) return;
    ref.current.style.height = "auto";
    ref.current.style.height = Math.min(ref.current.scrollHeight, 160) + "px";
  };

  const sendText = () => {
    const text = val.trim();
    if (!text || loading) return;
    onSend(text);
    setVal("");
    if (ref.current) ref.current.style.height = "auto";
  };

  const sendImageFile = () => {
    if (!pickedImage || loading) return;
    const prompt = val.trim();
    onSendImage(pickedImage, prompt || undefined);
    setPickedImage(null);
    setVal("");
    if (fileRef.current) fileRef.current.value = "";
    if (ref.current) ref.current.style.height = "auto";
  };

  const handleMainSend = () => {
    if (pickedImage) {
      sendImageFile();
      return;
    }
    sendText();
  };

  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const okType = ["image/png", "image/jpeg", "image/jpg", "image/webp"].includes(file.type);
    if (!okType) {
      alert("Chỉ hỗ trợ PNG, JPG, JPEG, WEBP");
      e.target.value = "";
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      alert("Ảnh vượt quá 5MB");
      e.target.value = "";
      return;
    }

    setPickedImage(file);
  };

  const display = listening && interim ? val + (val ? " " : "") + interim : val;
  const canSend = pickedImage ? !loading : !!val.trim() && !loading;

  return (
    <div className="space-y-2">
      {listening && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-accent/5 border border-accent/20 rounded-xl animate-fade-up">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
          </span>
          <span className="text-xs text-accent">Đang nghe tiếng Việt...</span>
          {interim && (
            <span className="text-xs text-text-muted italic truncate max-w-[200px]">
              "{interim}"
            </span>
          )}
        </div>
      )}

      {pickedImage && (
        <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-xl border border-accent/20 bg-accent/5 animate-fade-up">
          <div className="flex items-center gap-2 min-w-0">
            <ImageIcon className="w-4 h-4 text-accent flex-shrink-0" />
            <div className="min-w-0">
              <p className="text-sm text-text-primary truncate">{pickedImage.name}</p>
              <p className="text-xs text-text-muted">
                {(pickedImage.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
          </div>

          <button
            onClick={() => {
              setPickedImage(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-red-400 hover:bg-surface-2 transition-colors"
            title="Bỏ ảnh"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div
        className={clsx(
          "flex items-end gap-2 px-3 py-2 rounded-2xl border transition-all duration-200",
          listening
            ? "border-accent/50 bg-accent/5"
            : "border-surface-3 bg-surface-1 focus-within:border-accent/40"
        )}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/webp"
          className="hidden"
          onChange={onPickFile}
        />

        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={loading}
          title="Gửi ảnh"
          className="flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all text-text-muted hover:text-accent hover:bg-accent/10 disabled:opacity-50"
        >
          <ImageIcon className="w-4 h-4" />
        </button>

        <textarea
          ref={ref}
          value={display}
          onChange={(e) => {
            setVal(e.target.value);
            resize();
          }}
          onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleMainSend();
            }
          }}
          placeholder={
            pickedImage
              ? "Thêm câu hỏi cho ảnh này, hoặc bấm gửi để phân tích..."
              : listening
                ? "Đang nhận giọng nói..."
                : hasDocs
                  ? "Hỏi về tài liệu đã ingest hoặc gửi ảnh để phân tích..."
                  : "Hỏi bất kỳ điều gì hoặc gửi ảnh..."
          }
          disabled={loading}
          rows={1}
          className="flex-1 bg-transparent resize-none outline-none text-sm text-text-primary placeholder:text-text-muted leading-6 max-h-40 disabled:opacity-60"
        />

        {supported && (
          <button
            onClick={() => (listening ? stop() : start())}
            disabled={loading}
            title={listening ? "Dừng ghi âm" : "Nhập bằng giọng nói (tiếng Việt)"}
            className={clsx(
              "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all disabled:opacity-50",
              listening
                ? "bg-accent text-surface-DEFAULT scale-110 shadow-lg shadow-accent/25"
                : "text-text-muted hover:text-accent hover:bg-accent/10"
            )}
          >
            {listening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
          </button>
        )}

        <button
          onClick={handleMainSend}
          disabled={!canSend}
          className={clsx(
            "flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all",
            canSend
              ? "bg-accent text-surface-DEFAULT hover:bg-accent-dim hover:scale-105"
              : "bg-surface-3 text-text-muted cursor-not-allowed"
          )}
          title={pickedImage ? "Gửi ảnh" : "Gửi tin nhắn"}
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        </button>
      </div>

      <p className="text-xs text-center text-text-muted opacity-40">
        Enter gửi · Shift+Enter xuống dòng
        {supported && " · 🎤 hỗ trợ giọng nói tiếng Việt"}
        {" · 🖼️ hỗ trợ PNG/JPG/WEBP"}
      </p>
    </div>
  );
}