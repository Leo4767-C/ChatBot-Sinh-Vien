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
        <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-xl animate-fade-up">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-600" />
          </span>
          <span className="text-xs text-blue-600 font-medium">Đang nghe tiếng Việt...</span>
          {interim && (
            <span className="text-xs text-slate-500 italic truncate max-w-[200px]">
              "{interim}"
            </span>
          )}
        </div>
      )}

      {pickedImage && (
        <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-xl border border-blue-200 bg-blue-50 animate-fade-up">
          <div className="flex items-center gap-2 min-w-0">
            <ImageIcon className="w-4 h-4 text-blue-600 flex-shrink-0" />
            <div className="min-w-0">
              <p className="text-sm text-slate-800 font-medium truncate">{pickedImage.name}</p>
              <p className="text-xs text-slate-500">
                {(pickedImage.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
          </div>

          <button
            onClick={() => {
              setPickedImage(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-red-500 hover:bg-white shadow-sm transition-colors"
            title="Bỏ ảnh"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div
        className={clsx(
          "flex items-end gap-2 px-3 py-2 rounded-2xl border transition-all duration-200 shadow-sm",
          listening
            ? "border-blue-400 bg-blue-50 ring-2 ring-blue-100"
            : "border-slate-300 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100"
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
          className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all text-slate-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
        >
          <ImageIcon className="w-5 h-5" />
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
              ? "Thêm câu hỏi cho ảnh này..."
              : listening
                ? "Đang nhận giọng nói..."
                : "Hỏi bất kỳ điều gì..."
          }
          disabled={loading}
          rows={1}
          className="flex-1 bg-transparent resize-none outline-none text-[15px] text-slate-800 placeholder:text-slate-400 leading-6 max-h-40 py-1.5 disabled:opacity-60"
        />

        {supported && (
          <button
            onClick={() => (listening ? stop() : start())}
            disabled={loading}
            title={listening ? "Dừng ghi âm" : "Nhập bằng giọng nói"}
            className={clsx(
              "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-50",
              listening
                ? "bg-blue-600 text-white scale-110 shadow-lg shadow-blue-600/30"
                : "text-slate-400 hover:text-blue-600 hover:bg-blue-50"
            )}
          >
            {listening ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
          </button>
        )}

        <button
          onClick={handleMainSend}
          disabled={!canSend}
          className={clsx(
            "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all",
            canSend
              ? "bg-blue-600 text-white hover:bg-blue-700 hover:scale-105 shadow-md shadow-blue-200"
              : "bg-slate-100 text-slate-400 cursor-not-allowed"
          )}
          title={pickedImage ? "Gửi ảnh" : "Gửi tin nhắn"}
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4 ml-0.5" />}
        </button>
      </div>

      <p className="text-xs text-center text-slate-400 font-medium">
        Enter để gửi · Shift+Enter để xuống dòng
      </p>
    </div>
  );
}