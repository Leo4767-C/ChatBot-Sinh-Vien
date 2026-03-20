"use client";
import { useState, useCallback, useRef, useEffect } from "react";

export function useVoiceInput(onFinal?: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef<any>(null);

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
    const rec = new SR();
    rec.lang = "vi-VN";
    rec.continuous = false;
    rec.interimResults = true;
    rec.onresult = (e: any) => {
      let fin = "", tmp = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        e.results[i].isFinal ? (fin += e.results[i][0].transcript) : (tmp += e.results[i][0].transcript);
      }
      setInterim(fin || tmp);
      if (fin && onFinal) onFinal(fin.trim());
    };
    rec.onend = () => { setListening(false); setInterim(""); };
    rec.onerror = () => { setListening(false); setInterim(""); };
    rec.start();
    recRef.current = rec;
    setListening(true);
    setInterim("");
  }, [onFinal]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    setListening(false);
  }, []);

  return { listening, supported, interim, start, stop };
}