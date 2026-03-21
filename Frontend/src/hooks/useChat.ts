"use client";

import { useCallback, useState } from "react";
import { Message } from "@/lib/types";
import { streamChat, uploadImage } from "@/lib/api";

export function useChat(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback((history: Message[]) => {
    setMessages(history || []);
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setError("");
    setLoading(false);
  }, []);

  const finishLastModel = useCallback(() => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "model") last.isStreaming = false;
      return next;
    });
  }, []);

  const send = useCallback(
    async (question: string) => {
      if (!question.trim() || !sessionId) return;

      setError("");
      setLoading(true);

      setMessages((prev) => [
        ...prev,
        { role: "user", content: question },
        { role: "model", content: "", isStreaming: true, sources: [], images: [] },
      ]);

      try {
        await streamChat(
          sessionId,
          question,
          (text) => {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "model") {
                last.content += text;
              }
              return next;
            });
          },
          (sources) => {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "model") {
                last.sources = sources;
              }
              return next;
            });
          },
          () => {
            finishLastModel();
            setLoading(false);
          },
          (err) => {
            setError(err);
            finishLastModel();
            setLoading(false);
          },
          (images) => {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "model") {
                last.images = images;
              }
              return next;
            });
          }
        );
      } catch (e) {
        console.error(e);
        setError("Không thể gửi tin nhắn. Kiểm tra backend hoặc mạng.");
        finishLastModel();
        setLoading(false);
      }
    },
    [sessionId, finishLastModel]
  );

  const sendImage = useCallback(
    async (file: File, question?: string) => {
      if (!file || !sessionId) return;

      setError("");
      setLoading(true);

      const tempUrl = URL.createObjectURL(file);
      const userText = question?.trim() || "Hãy đọc và tóm tắt nội dung trong ảnh này.";

      setMessages((prev) => [
        ...prev,
        { role: "user", content: userText, images: [tempUrl] },
        { role: "model", content: "", isStreaming: true, sources: [], images: [] },
      ]);

      try {
        const res = await uploadImage(sessionId, file, question);

        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];

          if (last && last.role === "model") {
            last.content = res.answer;
            last.isStreaming = false;
            last.images = [];
          }

          return next;
        });
      } catch (e) {
        console.error(e);
        setError(e instanceof Error ? e.message : "Không thể phân tích ảnh.");
        finishLastModel();
      } finally {
        setLoading(false);
      }
    },
    [sessionId, finishLastModel]
  );

  return {
    messages,
    loading,
    error,
    send,
    sendImage,
    load,
    clear,
  };
}