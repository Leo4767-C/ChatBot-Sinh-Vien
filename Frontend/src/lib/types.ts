export type ChatSource = {
  id?: string | number;
  title?: string;
  name?: string;
  filename?: string;
  file_name?: string;
  source?: string;
};

export type Message = {
  role: "user" | "model";
  content: string;
  isStreaming?: boolean;
  sources?: ChatSource[];
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
  image_url?: string;
  sources?: ChatSource[];
};