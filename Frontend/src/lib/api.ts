const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSource {
  id?: string | number;
  title?: string;
  name?: string;
  filename?: string;
  file_name?: string;
  source?: string;
}

export interface ImageChatResponse {
  ok: boolean;
  answer: string;
  image_url?: string;
  sources?: ChatSource[];
}

export async function createSession(): Promise<ChatSession> {
  const r = await fetch(`${BASE}/api/sessions/`, { method: "POST" });
  if (!r.ok) throw new Error("Không tạo được session");
  return r.json();
}

export async function getSessions(): Promise<ChatSession[]> {
  const r = await fetch(`${BASE}/api/sessions/`);
  if (!r.ok) return [];
  return r.json();
}

export async function getHistory(sid: string) {
  const r = await fetch(`${BASE}/api/sessions/${sid}/history`);
  if (!r.ok) return [];
  return r.json();
}

export async function deleteSession(sid: string) {
  await fetch(`${BASE}/api/sessions/${sid}`, { method: "DELETE" });
}

export async function uploadImage(
  sessionId: string,
  file: File,
  question?: string
): Promise<ImageChatResponse> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("image", file);
  if (question?.trim()) form.append("question", question.trim());

  const r = await fetch(`${BASE}/api/chat/image`, {
    method: "POST",
    body: form,
  });

  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(text || "Không gửi được ảnh lên backend");
  }

  return r.json();
}

export async function streamChat(
  sessionId: string,
  question: string,
  onChunk: (t: string) => void,
  onSources: (s: ChatSource[]) => void,
  onDone: () => void,
  onError: (e: string) => void,
  onImages?: (urls: string[]) => void
) {
  let r: Response;
  try {
    r = await fetch(`${BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
    });
  } catch {
    onError("Không kết nối được backend. Kiểm tra FastAPI port 8000.");
    return;
  }

  if (!r.ok || !r.body) {
    onError(`Lỗi server ${r.status}`);
    return;
  }

  const reader = r.body.getReader();
  const dec = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += dec.decode(value, { stream: true });

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data: ")) continue;

      const data = line.slice(6);

      if (data === "[DONE]") {
        onDone();
        return;
      }

      if (data.startsWith("[SOURCES]")) {
        try {
          onSources(JSON.parse(data.slice(9)));
        } catch {}
        continue;
      }

      if (data.startsWith("[IMAGES]")) {
        try {
          const urls: string[] = JSON.parse(data.slice(8));
          if (onImages && urls.length > 0) onImages(urls);
        } catch {}
        continue;
      }

      // Backend gửi delta dưới dạng JSON string (json.dumps) để newline không
      // phá vỡ SSE protocol. Parse ở đây để khôi phục đúng \n, tab, unicode.
      try {
        onChunk(JSON.parse(data));
      } catch {
        // Fallback cho backend cũ gửi text thô với \n escaped
        onChunk(data.replace(/\\n/g, "\n"));
      }
    }
  }

  onDone();
}