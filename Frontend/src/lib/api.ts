const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatSession { id:string; title:string; created_at:string; updated_at:string; }

export async function createSession(): Promise<ChatSession> {
  const r = await fetch(`${BASE}/api/sessions/`, {method:"POST"});
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
  await fetch(`${BASE}/api/sessions/${sid}`, {method:"DELETE"});
}

export async function streamChat(
  sessionId: string,
  question: string,
  onChunk: (t: string) => void,
  onSources: (s: string[]) => void,
  onDone: () => void,
  onError: (e: string) => void,
  onImages?: (urls: string[]) => void,   // ← callback mới cho [IMAGES]
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
  if (!r.ok) { onError(`Lỗi server ${r.status}`); return; }

  const reader = r.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);

      if (data === "[DONE]") { onDone(); return; }

      // Parse [SOURCES]
      if (data.startsWith("[SOURCES]")) {
        try { onSources(JSON.parse(data.slice(9))); } catch {}
        continue;
      }

      // Parse [IMAGES] — không để lọt ra thành text
      if (data.startsWith("[IMAGES]")) {
        try {
          const urls: string[] = JSON.parse(data.slice(8));
          if (onImages && urls.length > 0) onImages(urls);
        } catch {}
        continue;
      }

      // Text chunk bình thường
      onChunk(data.replace(/\\n/g, "\n"));
    }
  }
  onDone();
}