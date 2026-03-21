"use client";
import { useState, useCallback, useRef, useEffect } from "react";

export function useVoiceInput(onFinal?: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const [interim, setInterim] = useState("");
  
  const recRef = useRef<any>(null);
  const onFinalRef = useRef(onFinal);

  // QUAN TRỌNG NHẤT: Lưu hàm onFinal vào Ref để React không bị load lại liên tục
  useEffect(() => {
    onFinalRef.current = onFinal;
  }, [onFinal]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      setSupported(!!SR);
    }
  }, []);

  const start = useCallback(() => {
    if (typeof window === "undefined") return;
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;

    if (recRef.current) {
      try { recRef.current.stop(); } catch (e) {}
    }

    const rec = new SR();
    rec.lang = "vi-VN";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => {
      setListening(true);
      setInterim("");
    };

    rec.onresult = (e: any) => {
      let fin = "", tmp = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript;
        else tmp += e.results[i][0].transcript;
      }
      
      setInterim(tmp); // Chỉ hiện chữ đang nói dở

      // Nếu đã chốt câu, đẩy lên UI thông qua Ref
      if (fin && onFinalRef.current) {
        onFinalRef.current(fin.trim());
      }
    };

    rec.onerror = (e: any) => {
      if (e.error !== "no-speech") setListening(false);
    };

    rec.onend = () => {
      setListening(false);
      setInterim("");
    };

    try {
      rec.start();
      recRef.current = rec;
    } catch (err) {}
  }, []);

  const stop = useCallback(() => {
    if (recRef.current) {
      try { recRef.current.stop(); } catch (e) {}
    }
    setListening(false);
    setInterim("");
  }, []);

  return { listening, supported, interim, start, stop };
}