"use client";
import { useState, useCallback, useRef } from "react";
import { Message } from "@/lib/types";
import { streamChat } from "@/lib/api";

export function useChat(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const abort = useRef(false);

  const send = useCallback(async (question: string) => {
    if (loading || !question.trim() || !sessionId) return;
    setError(null); setLoading(true); abort.current = false;

    setMessages(p => [...p, { role: "user", content: question }]);
    setMessages(p => [...p, { role: "model", content: "", isStreaming: true }]);

    let acc = "";
    let sources: string[] = [];
    let imageUrls: string[] = [];

    await streamChat(
      sessionId,
      question,
      // onChunk — text thông thường
      chunk => {
        if (abort.current) return;
        acc += chunk;
        setMessages(p => {
          const n = [...p];
          n[n.length - 1] = { ...n[n.length - 1], content: acc, isStreaming: true };
          return n;
        });
      },
      // onSources
      s => { sources = s; },
      // onDone
      () => {
        setMessages(p => {
          const n = [...p];
          n[n.length - 1] = {
            role: "model",
            content: acc,
            sources: sources.length ? sources : undefined,
            isStreaming: false,
          };
          return n;
        });
        setLoading(false);
      },
      // onError
      err => {
        setError(err);
        setMessages(p => p.slice(0, -1));
        setLoading(false);
      },
      // onImages — lưu lại nhưng không cần làm gì thêm
      // Gemini đã chèn ảnh vào text qua markdown, [IMAGES] chỉ là metadata
      urls => { imageUrls = urls; },
    );
  }, [sessionId, loading]);

  const load = useCallback((h: { role: "user" | "model"; content: string }[]) => {
    setMessages(h.map(m => ({ role: m.role, content: m.content })));
  }, []);

  const clear = useCallback(() => {
    abort.current = true;
    setMessages([]); setError(null); setLoading(false);
  }, []);

  return { messages, loading, error, send, load, clear };
}