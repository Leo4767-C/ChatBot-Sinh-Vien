export interface Message {
  role: "user" | "model";
  content: string;
  sources?: string[];
  isStreaming?: boolean;
}
export interface ChatSession {
  id: string; title: string;
  created_at: string; updated_at: string;
}
