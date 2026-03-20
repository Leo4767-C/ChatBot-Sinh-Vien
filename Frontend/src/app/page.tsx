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
  "Điều kiện tốt nghiệp gồm những gì?",
  "Giải thích Machine Learning kèm hình ảnh minh họa",
  "Cách đăng ký tín chỉ học kỳ mới",
  "Quy định điểm rèn luyện sinh viên",
];

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sid, setSid]           = useState<string | null>(null);
  const [sidebarOpen, setSidebar] = useState(true);
  const [initLoading, setInit]  = useState(true);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const sidRef     = useRef<string | null>(null); // ref để tránh stale closure
  const [, startTransition] = useTransition();

  const { messages, loading, error, send, load, clear } = useChat(sid || "");

  // Sync ref với state
  useEffect(() => { sidRef.current = sid; }, [sid]);

  // Load sessions ban đầu
  useEffect(() => {
    getSessions()
      .then(s => setSessions(s))
      .catch(() => {})
      .finally(() => setInit(false));
  }, []);

  // Auto scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const refreshSessions = useCallback(() => {
    // Dùng startTransition để không block UI
    startTransition(() => {
      getSessions().then(setSessions).catch(() => {});
    });
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
    if (sidRef.current === id) {
      setSid(null);
      sidRef.current = null;
      clear();
    }
  }, [clear]);

  // Fix chính: dùng ref để luôn có sid mới nhất, không bị stale closure
  const handleSend = useCallback(async (text: string) => {
    let id = sidRef.current;

    // Tạo session mới ngay nếu chưa có — không cần chọn suggestion trước
    if (!id) {
      const s = await createSession();
      setSessions(p => [s, ...p]);
      setSid(s.id);
      sidRef.current = s.id;
      id = s.id;
    }

    await send(text);

    // Refresh title sidebar sau khi bot trả lời xong, không block gửi tin
    refreshSessions();
  }, [send, refreshSessions]);

  return (
    <div className="flex h-screen bg-surface-DEFAULT overflow-hidden">

      {/* ── Sidebar ───────────────────────────────────── */}
      <aside className={clsx(
        "flex flex-col border-r border-surface-3 bg-surface-1 transition-all duration-300 flex-shrink-0",
        sidebarOpen ? "w-64" : "w-0 overflow-hidden"
      )}>
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-surface-3">
          <div className="w-7 h-7 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-accent"/>
          </div>
          <div>
            <p className="text-sm font-bold text-text-primary">NCKH StudyBot</p>
            <p className="text-xs text-text-muted">RAG · Voice · Hình ảnh</p>
          </div>
        </div>

        {/* Feature badges */}
        <div className="flex gap-1.5 px-3 py-2">
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text-secondary">
            <span style={{fontSize:10}}>🎤</span> Voice
          </span>
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text-secondary">
            <ImageIcon className="w-2.5 h-2.5"/> Ảnh
          </span>
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text-secondary">
            <BookOpen className="w-2.5 h-2.5"/> RAG
          </span>
        </div>

        {/* New chat */}
        <div className="px-3 pb-2">
          <button onClick={newSession}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm bg-accent/10 border border-accent/20 text-accent hover:bg-accent/20 transition-colors">
            <Plus className="w-4 h-4"/> Cuộc trò chuyện mới
          </button>
        </div>

        {/* Sessions list */}
        <div className="flex-1 overflow-y-auto px-2 space-y-0.5 py-1">
          {initLoading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="w-4 h-4 text-accent animate-spin"/>
            </div>
          ) : sessions.length === 0 ? (
            <p className="text-xs text-text-muted text-center py-6 px-4">
              Chưa có cuộc trò chuyện nào
            </p>
          ) : sessions.map(s => (
            <button key={s.id} onClick={() => selectSession(s)}
              className={clsx(
                "w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-xs transition-colors group",
                s.id === sid
                  ? "bg-accent/10 text-accent"
                  : "text-text-secondary hover:bg-surface-2 hover:text-text-primary"
              )}>
              <MessageSquare className="w-3.5 h-3.5 flex-shrink-0"/>
              <span className="flex-1 truncate">{s.title}</span>
              <button
                onClick={e => delSession(s.id, e)}
                className="opacity-0 group-hover:opacity-100 hover:text-red-400 transition-all p-0.5 rounded">
                <Trash2 className="w-3 h-3"/>
              </button>
            </button>
          ))}
        </div>

        {/* Tip */}
        <div className="p-3 border-t border-surface-3">
          <p className="text-xs text-text-muted leading-relaxed">
            💡 Chạy{" "}
            <code className="bg-surface-3 px-1 rounded text-accent">python ingest.py</code>{" "}
            để thêm tài liệu
          </p>
        </div>
      </aside>

      {/* ── Main ──────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">

        {/* Header */}
        <header className="flex items-center gap-3 px-4 py-3 border-b border-surface-3 bg-surface-1/60 backdrop-blur-sm flex-shrink-0">
          <button
            onClick={() => setSidebar(p => !p)}
            className="text-text-muted hover:text-text-primary transition-colors p-1 rounded-lg hover:bg-surface-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
          </button>
          <div className="flex-1">
            <h1 className="text-sm font-semibold text-text-primary">
              Trợ lý nghiên cứu khoa học AI
            </h1>
            <p className="text-xs text-text-muted">
              Hỏi bằng văn bản hoặc giọng nói · Bot trả lời kèm hình ảnh minh họa
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse"/>
            <span className="text-xs text-text-secondary hidden sm:block">Gemini 2.5</span>
          </div>
        </header>

        {/* Messages */}
        <div
          className="flex-1 overflow-y-auto px-4 py-6"
          style={{scrollbarWidth:"thin"}}>
          <div className="max-w-2xl mx-auto space-y-6">
            {messages.length === 0 && !loading && (
              <Welcome onSuggest={handleSend}/>
            )}
            {messages.map((m, i) => (
              <MessageBubble key={i} msg={m}/>
            ))}
            {loading && messages[messages.length - 1]?.role !== "model" && (
              <Typing/>
            )}
            {error && (
              <div className="p-4 bg-red-950/30 border border-red-800/40 rounded-2xl text-sm text-red-300">
                {error}
              </div>
            )}
            <div ref={bottomRef}/>
          </div>
        </div>

        {/* Input — luôn hiển thị, không cần chọn suggestion mới dùng được */}
        <div className="border-t border-surface-3 bg-surface-1/80 px-4 py-3 flex-shrink-0">
          <div className="max-w-2xl mx-auto">
            <ChatInput onSend={handleSend} loading={loading} hasDocs={true}/>
          </div>
        </div>

      </main>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────

function Typing() {
  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-surface-2 border border-surface-3 flex items-center justify-center text-base">
        🤖
      </div>
      <div className="bg-surface-1 border border-surface-3 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1.5 items-center">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="w-2 h-2 rounded-full bg-accent animate-pulse"
              style={{animationDelay: `${i * 0.16}s`}}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function Welcome({ onSuggest }: { onSuggest: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center py-10 gap-6 animate-fade-up">
      <div className="relative">
        <div className="w-16 h-16 rounded-2xl bg-accent/10 border-2 border-accent/30 flex items-center justify-center text-3xl">
          🎓
        </div>
        <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-lg bg-accent flex items-center justify-center">
          <Sparkles className="w-3 h-3 text-surface-DEFAULT"/>
        </div>
      </div>

      <div className="text-center space-y-2">
        <h2 className="text-xl font-bold text-text-primary">Xin chào, Nhà nghiên cứu!</h2>
        <p className="text-text-secondary text-sm max-w-sm leading-relaxed">
          Hỏi bằng{" "}
          <span className="text-accent font-medium">văn bản</span>{" "}
          hoặc nhấn{" "}
          <span className="text-accent font-medium">🎤 giọng nói</span>.
          Bot trả lời kèm{" "}
          <span className="text-accent font-medium">hình ảnh minh họa</span> khi cần.
        </p>
      </div>

      {/* Suggestions chỉ là gợi ý nhanh, không bắt buộc phải click */}
      <div className="w-full max-w-md space-y-2">
        <p className="text-xs text-text-muted text-center mb-1">Gợi ý câu hỏi</p>
        {SUGGESTIONS.map((q, i) => (
          <button
            key={i}
            onClick={() => onSuggest(q)}
            className="w-full text-left px-4 py-2.5 rounded-xl text-sm bg-surface-1 border border-surface-3 text-text-secondary hover:border-accent/40 hover:text-text-primary transition-all">
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}