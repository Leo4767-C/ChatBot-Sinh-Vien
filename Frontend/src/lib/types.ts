export type Message = {
  role: "user" | "model";
  content: string;
  isStreaming?: boolean;
  sources?: string[];
  images?: string[];
};

export type ChatSession = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type ImageChatResponse = {
  ok: boolean;
  answer: string;
  image_url: string;
};