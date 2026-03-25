'use client';

import React, { useRef, useEffect, useState } from 'react';
import Image from 'next/image';
import { useChat } from '@/hooks/useChat';
import MessageBubble from '@/components/chat/MessageBubble';
import ChatInput from '@/components/chat/ChatInput';
import {
  Plus,
  MessageSquare,
  Menu,
  Clock,
  ChevronRight,
  Loader2,
  PanelLeft,
  Trash2,
} from 'lucide-react';

const SUGGESTIONS = [
  'Quy chế thi lại, học lại như thế nào?',
  'Điều kiện để được xét học bổng khuyến khích học tập?',
  'Chuẩn đầu ra Tiếng Anh quy định như thế nào?',
  'Hướng dẫn cách kết nối Wifi của trường?',
];

const API_BASE_URL = 'http://127.0.0.1:8000/api';

type HistoryItem = {
  id: string;
  title?: string;
};

export default function Home() {
  const [sessionId, setSessionId] = useState('');
  const { messages, send, sendImage, loading, clear, load } = useChat(sessionId);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isDesktopSidebarOpen, setIsDesktopSidebarOpen] = useState(true);

  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [chatHistory, setChatHistory] = useState<HistoryItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    handleNewChat();
  }, []);

  useEffect(() => {
    if (messages.length > 0 && messages.length <= 2 && !loading) {
      fetchSessions();
    }
  }, [messages.length, loading]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/sessions/`);
      if (res.ok) {
        const data = await res.json();
        setChatHistory(data);
      }
    } catch (error) {
      console.error('Không thể kết nối đến Backend để lấy lịch sử:', error);
    }
  };

  const handleNewChat = async () => {
    clear();
    setIsMobileSidebarOpen(false);

    try {
      const res = await fetch(`${API_BASE_URL}/sessions/`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setSessionId(data.id);
      } else {
        setSessionId('session-' + Math.random().toString(36).substring(7));
      }
    } catch (error) {
      console.error('Lỗi tạo session:', error);
      setSessionId('session-' + Math.random().toString(36).substring(7));
    }

    fetchSessions();
  };

  const handleSelectHistory = async (id: string) => {
    setIsMobileSidebarOpen(false);
    if (id === sessionId) return;

    setIsLoadingHistory(true);
    try {
      const res = await fetch(`${API_BASE_URL}/sessions/${id}/history`);
      if (res.ok) {
        const pastMessages = await res.json();
        setSessionId(id);
        load(pastMessages);
      }
    } catch (error) {
      console.error('Lỗi khi lấy tin nhắn:', error);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleDeleteChat = async (
    id: string,
    e: React.MouseEvent<HTMLButtonElement>
  ) => {
    e.stopPropagation();

    setDeletingId(id);
    try {
      const res = await fetch(`${API_BASE_URL}/sessions/${id}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error('Xóa cuộc trò chuyện thất bại');
      }

      if (id === sessionId) {
        await handleNewChat();
      } else {
        await fetchSessions();
      }
    } catch (error) {
      console.error('Lỗi khi xóa cuộc trò chuyện:', error);
      alert('Không thể xóa cuộc trò chuyện. Vui lòng thử lại.');
    } finally {
      setDeletingId(null);
    }
  };

  const handleSuggestionClick = (text: string) => {
    send(text);
  };

  const renderThinkingBubble = () => (
    <div className="flex w-full justify-start">
      <div className="flex items-center gap-3 text-blue-600 text-sm bg-white px-5 py-3 rounded-3xl shadow-sm border border-slate-100 max-w-max">
        <div className="flex gap-1.5">
          <div
            className="w-2 h-2 bg-blue-500 rounded-full animate-bounce"
            style={{ animationDelay: '0ms' }}
          />
          <div
            className="w-2 h-2 bg-blue-500 rounded-full animate-bounce"
            style={{ animationDelay: '150ms' }}
          />
          <div
            className="w-2 h-2 bg-blue-500 rounded-full animate-bounce"
            style={{ animationDelay: '300ms' }}
          />
        </div>
        <span className="font-medium animate-pulse">Đang suy nghĩ...</span>
      </div>
    </div>
  );

  return (
    <div className="h-screen bg-slate-100 text-slate-800 flex overflow-hidden">
      {isMobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setIsMobileSidebarOpen(false)}
        />
      )}

      <aside
        className={`
          fixed lg:static inset-y-0 left-0 z-50
          ${isDesktopSidebarOpen ? 'w-[290px]' : 'w-0 lg:w-[88px]'}
          ${isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
          lg:translate-x-0
          transition-all duration-300 ease-in-out
          bg-white border-r border-slate-200 flex flex-col shadow-xl lg:shadow-none
          overflow-hidden
        `}
      >
        <div className="p-4 border-b border-slate-100">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-4 transition-all shadow-sm"
          >
            <Plus className="w-5 h-5" />
            {isDesktopSidebarOpen ? <span>Đoạn chat mới</span> : null}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 pt-2 pb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              Gần đây
            </span>
          </p>

          {chatHistory.length === 0 ? (
            <p className="text-xs text-center text-slate-400 mt-4 italic">
              Chưa có lịch sử
            </p>
          ) : (
            chatHistory.map((chat) => (
              <div
                key={chat.id}
                onClick={() => handleSelectHistory(chat.id)}
                className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl transition-colors group cursor-pointer ${
                  sessionId === chat.id
                    ? 'bg-blue-50 text-blue-700'
                    : 'hover:bg-sky-50 text-slate-600 hover:text-blue-700'
                } ${deletingId === chat.id ? 'opacity-60 pointer-events-none' : ''}`}
              >
                <MessageSquare
                  className={`w-4 h-4 flex-shrink-0 ${
                    sessionId === chat.id
                      ? 'text-blue-600'
                      : 'opacity-50 group-hover:opacity-100 group-hover:text-blue-600'
                  }`}
                />

                <span className="text-sm truncate flex-1 font-medium">
                  {chat.title || 'Trò chuyện mới'}
                </span>

                <button
                  onClick={(e) => handleDeleteChat(chat.id, e)}
                  disabled={deletingId === chat.id}
                  title="Xóa cuộc trò chuyện"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-500 disabled:opacity-50"
                >
                  {deletingId === chat.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </button>
              </div>
            ))
          )}
        </div>

        <div className="p-4 border-t border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-xs">
              SV
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-slate-700 truncate">
                Sinh viên TLU
              </p>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0 relative">
        <header className="flex items-center justify-between px-4 md:px-6 py-3 md:py-4 bg-white/80 backdrop-blur-md shadow-sm border-b border-slate-100 z-10 sticky top-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsMobileSidebarOpen(true)}
              className="lg:hidden p-2 -ml-2 text-slate-500 hover:text-blue-600 hover:bg-sky-50 rounded-lg transition-colors"
            >
              <Menu className="w-6 h-6" />
            </button>

            <button
              onClick={() => setIsDesktopSidebarOpen(!isDesktopSidebarOpen)}
              className="hidden lg:block p-2 -ml-2 text-slate-500 hover:text-blue-600 hover:bg-sky-50 rounded-lg transition-colors"
              title={isDesktopSidebarOpen ? 'Đóng thanh bên' : 'Mở thanh bên'}
            >
              <PanelLeft className="w-6 h-6" />
            </button>

            <div className="relative w-10 h-10 md:w-12 md:h-12 flex-shrink-0 bg-sky-100 rounded-full p-1.5 shadow-inner">
              <Image
                src="/logo-tlu.png"
                alt="Logo Đại học Thủy Lợi"
                fill
                className="object-contain"
                priority
              />
            </div>

            <div className="flex flex-col">
              <h1 className="text-lg md:text-xl font-extrabold text-blue-700 leading-tight tracking-tight">
                Chatbot hỗ trợ sinh viên
              </h1>
            </div>
          </div>

          <button
            onClick={handleNewChat}
            className="hidden sm:inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:text-blue-600 hover:border-blue-200 hover:bg-blue-50 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Đoạn chat mới
          </button>
        </header>

        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:px-24 xl:px-48 scroll-smooth">
          <div className="flex flex-col gap-6 pb-6 max-w-4xl mx-auto">
            {isLoadingHistory ? (
              <div className="flex flex-col items-center justify-center h-full mt-32 text-slate-400">
                <Loader2 className="w-8 h-8 animate-spin mb-4 text-blue-500" />
                <p>Đang tải cuộc trò chuyện...</p>
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full mt-10 md:mt-20 text-center animate-fade-in bg-white p-6 md:p-10 rounded-3xl shadow-sm border border-slate-100">
                <div className="w-20 h-20 mb-6 relative opacity-90 p-3 bg-sky-50 rounded-full">
                  <Image
                    src="/logo-tlu.png"
                    alt="TLU Logo"
                    fill
                    className="object-contain"
                  />
                </div>

                <h2 className="text-2xl md:text-3xl font-bold text-slate-800 mb-3 tracking-tight">
                  Xin chào, sinh viên TLU!
                </h2>

                <p className="text-slate-500 max-w-lg leading-relaxed text-sm md:text-base mb-8">
                  Hôm nay bạn cần hỗ trợ gì về quy chế, điểm chuẩn, hay các thông
                  tin học vụ? Hãy chọn một câu hỏi mẫu hoặc nhập câu hỏi của bạn
                  bên dưới nhé.
                </p>

                <div className="w-full max-w-2xl text-left">
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                    Gợi ý câu hỏi <ChevronRight className="w-4 h-4" />
                  </p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {SUGGESTIONS.map((text, index) => (
                      <button
                        key={index}
                        onClick={() => handleSuggestionClick(text)}
                        className="group text-left rounded-2xl border border-slate-200 bg-white p-4 hover:border-blue-200 hover:bg-blue-50/70 hover:shadow-sm transition-all"
                      >
                        <div className="flex items-start gap-3">
                          <ChevronRight className="w-4 h-4 mt-0.5 text-blue-400 group-hover:text-blue-600 flex-shrink-0" />
                          <span>{text}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              messages.map((msg, index) => {
                const isLast = index === messages.length - 1;
                const showThinkingAfterThis = loading && isLast && msg.role === 'user';

                return (
                  <React.Fragment key={index}>
                    <div
                      className={`flex w-full ${
                        msg.role === 'user' ? 'justify-end' : 'justify-start'
                      }`}
                    >
                      <MessageBubble msg={msg} />
                    </div>

                    {showThinkingAfterThis && renderThinkingBubble()}
                  </React.Fragment>
                );
              })
            )}

            <div ref={messagesEndRef} />
          </div>
        </main>

        <footer className="bg-white/80 backdrop-blur-md border-t border-slate-200 p-4 md:p-5">
          <div className="max-w-4xl mx-auto">
            <ChatInput
              onSend={send}
              onSendImage={sendImage}
              loading={loading}
              hasDocs={true}
            />
          </div>
        </footer>
      </div>
    </div>
  );
}