"use client";
import { useState, useEffect, useRef, useCallback, useTransition } from "react";
import { ChatSession } from "@/lib/types";
import { createSession, getSessions, getHistory, deleteSession } from "@/lib/api";
import { useChat } from "@/hooks/useChat";
import MessageBubble from "@/components/chat/MessageBubble";
import ChatInput from "@/components/chat/ChatInput";
import {
  Plus, Trash2, MessageSquare, Sparkles, Loader2, BookOpen, Image as ImageIcon
} from "lucide-react";
import clsx from "clsx";

const SUGGESTIONS = [
  "Học phí trường là bao nhiêu?",
  "Giải thích Machine Learning kèm hình ảnh minh họa",
  "Cách đăng ký tín chỉ học kỳ mới",
];

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sid, setSid]           = useState<string | null>(null);
  const [sidebarOpen, setSidebar] = useState(true);
  const [initLoading, setInit]  = useState(true);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const sidRef     = useRef<string | null>(null); 
  const [, startTransition] = useTransition();

  const { messages, loading, error, send, load, clear } = useChat(sid || "");

  useEffect(() => { sidRef.current = sid; }, [sid]);

  useEffect(() => {
    getSessions().then(s => setSessions(s)).catch(() => {}).finally(() => setInit(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const refreshSessions = useCallback(() => {
    startTransition(() => { getSessions().then(setSessions).catch(() => {}); });
  }, []);

  const newSession = useCallback(async () => {
    const s = await createSession();
    setSessions(p => [s, ...p]);
    setSid(s.id);
    sidRef.current = s.id;
    clear();
  }, [clear]);

  const selectSession = useCallback(async (s: ChatSession) => {
    setSid(s.id);
    sidRef.current = s.id;
    clear();
    const h = await getHistory(s.id).catch(() => []);
    load(h);
  }, [clear, load]);

  const delSession = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await deleteSession(id);
    setSessions(p => p.filter(s => s.id !== id));
    if (sidRef.current === id) { setSid(null); sidRef.current = null; clear(); }
  }, [clear]);

  const handleSend = useCallback(async (text: string) => {
    let id = sidRef.current;
    if (!id) {
      const s = await createSession();
      setSessions(p => [s, ...p]);
      setSid(s.id);
      sidRef.current = s.id;
      id = s.id;
    }
    await send(text);
    refreshSessions();
  }, [send, refreshSessions]);

  return (
    <div className="flex h-screen bg-surface-DEFAULT overflow-hidden">
      <aside className={clsx("flex flex-col border-r border-surface-3 bg-surface-1 transition-all duration-300 flex-shrink-0", sidebarOpen ? "w-64" : "w-0 overflow-hidden")}>
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-surface-3">
          <div className="w-7 h-7 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center"><Sparkles className="w-3.5 h-3.5 text-accent"/></div>
          <div>
            <p className="text-sm font-bold text-text-primary">NCKH StudyBot</p>
            <p className="text-xs text-text-muted">RAG · Voice · Hình ảnh</p>
          </div>
        </div>
        <div className="px-3 py-4">
          <button onClick={newSession} className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm bg-accent/10 border border-accent/20 text-accent hover:bg-accent/20 transition-colors">
            <Plus className="w-4 h-4"/> Chat mới
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
          {initLoading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-4 h-4 text-accent animate-spin"/></div>
          ) : sessions.map(s => (
            <button key={s.id} onClick={() => selectSession(s)} className={clsx("w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-xs transition-colors group", s.id === sid ? "bg-accent/10 text-accent" : "text-text-secondary hover:bg-surface-2")}>
              <MessageSquare className="w-3.5 h-3.5 flex-shrink-0"/>
              <span className="flex-1 truncate">{s.title}</span>
              <Trash2 onClick={e => delSession(s.id, e)} className="opacity-0 group-hover:opacity-100 hover:text-red-400 w-3 h-3 transition-all"/>
            </button>
          ))}
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="flex items-center gap-3 px-4 py-3 border-b border-surface-3 bg-surface-1/60 backdrop-blur-sm">
          <button onClick={() => setSidebar(p => !p)} className="text-text-muted hover:text-text-primary p-1 rounded-lg hover:bg-surface-2">☰</button>
          <div className="flex-1"><h1 className="text-sm font-semibold">Trợ lý NCKH</h1></div>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="max-w-2xl mx-auto space-y-6">
            {messages.length === 0 && !loading && (
              <div className="flex flex-col items-center py-10 gap-6">
                <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center text-3xl">🎓</div>
                <h2 className="text-xl font-bold">Xin chào, Nhà nghiên cứu!</h2>
              </div>
            )}
            {messages.map((m, i) => <MessageBubble key={i} msg={m}/>)}
            {loading && messages[messages.length - 1]?.role !== "model" && <div className="text-xs text-accent animate-pulse">Đang tải...</div>}
            <div ref={bottomRef}/>
          </div>
        </div>

        <div className="border-t border-surface-3 bg-surface-1/80 px-4 py-3">
          <div className="max-w-2xl mx-auto">
            <ChatInput onSend={handleSend} loading={loading} hasDocs={true}/>
          </div>
        </div>
      </main>
    </div>
  );
}