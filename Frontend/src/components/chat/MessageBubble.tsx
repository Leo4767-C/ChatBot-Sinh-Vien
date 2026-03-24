"use client";

import { useMemo, useState } from "react";
import { Message } from "@/lib/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SHL } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { BookOpen, Image as ImageIcon } from "lucide-react";
import clsx from "clsx";

const API_BASE = "http://127.0.0.1:8000";

export default function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  const sources = useMemo(() => normalizeSources(msg.sources ?? []), [msg.sources]);

  const imageUrls = useMemo(() => {
    if (!msg.images || msg.images.length === 0) return [];

    return msg.images
      .map((url) => {
        if (!url) return "";
        if (url.startsWith("blob:")) return url;
        if (url.startsWith("http://") || url.startsWith("https://")) return url;
        if (url.startsWith("/")) return `${API_BASE}${url}`;
        return `${API_BASE}/${url}`;
      })
      .filter(Boolean);
  }, [msg.images]);

  return (
    <div
      className={clsx(
        "flex gap-3 animate-fade-up w-full",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {/* --- AVATAR --- */}
      <div
        className={clsx(
          "flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shadow-sm",
          isUser
            ? "bg-blue-100 text-blue-700" // Avatar SV
            : "bg-white border border-slate-200 text-xl shadow-sm" // Avatar Bot
        )}
      >
        {isUser ? "SV" : "🤖"}
      </div>

      {/* --- NỘI DUNG TIN NHẮN --- */}
      <div className="max-w-[85%] space-y-2">
        <div
          className={clsx(
            "px-5 py-4 text-sm md:text-base shadow-sm",
            isUser
              // STYLE TIN NHẮN USER: Nền xanh dương đậm, chữ trắng, bo góc đẹp
              ? "bg-blue-600 text-white rounded-3xl rounded-tr-sm border border-blue-700"
              // STYLE TIN NHẮN BOT: Nền trắng, chữ xám đen, bo góc mềm mại
              : "bg-white text-slate-800 rounded-3xl rounded-tl-sm border border-slate-100"
          )}
        >
          {isUser ? (
            <div>
              {msg.content?.trim() && (
                <p className="leading-relaxed whitespace-pre-wrap break-words">
                  {msg.content}
                </p>
              )}

              {imageUrls.length > 0 && (
                <div className="mt-3 space-y-3">
                  <div className="flex items-center gap-1.5 text-xs text-blue-100 opacity-90">
                    <ImageIcon className="w-4 h-4" />
                    <span>Ảnh bạn đã gửi</span>
                  </div>
                  <div className="grid gap-3">
                    {imageUrls.map((url, idx) => (
                      <Img
                        key={`${url}-${idx}`}
                        src={url}
                        alt={`Ảnh đã gửi ${idx + 1}`}
                        userImage
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>
              <MD content={msg.content} />

              {imageUrls.length > 0 && (
                <div className="mt-4 space-y-3">
                  <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
                    <ImageIcon className="w-4 h-4 text-blue-500" />
                    <span>Hình ảnh liên quan</span>
                  </div>

                  <div className="grid gap-3">
                    {imageUrls.map((url, idx) => (
                      <Img
                        key={`${url}-${idx}`}
                        src={url}
                        alt={`Hình minh họa ${idx + 1}`}
                        userImage={false}
                      />
                    ))}
                  </div>
                </div>
              )}

              {msg.isStreaming && (
                <span className="inline-block w-2.5 h-4 bg-blue-500 animate-pulse ml-1 rounded-sm align-text-bottom" />
              )}
            </div>
          )}
        </div>

        {/* --- HIỂN THỊ NGUỒN (SOURCES) --- */}
        {!isUser && sources.length > 0 && (
          <div className="flex items-start gap-1.5 px-3 mt-1">
            <BookOpen className="w-3.5 h-3.5 text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-slate-500 leading-relaxed">
              <span className="text-blue-600 font-medium">Nguồn tham khảo: </span>
              {sources.map((s, i) => (
                <span key={`${s}-${i}`}>
                  <span className="italic text-slate-600">{s}</span>
                  {i < sources.length - 1 && ", "}
                </span>
              ))}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ==========================================
// CÁC HÀM TIỆN ÍCH VÀ XỬ LÝ (Giữ nguyên logic gốc của bạn)
// ==========================================

function normalizeSources(rawSources: any[]): string[] {
  if (!Array.isArray(rawSources) || rawSources.length === 0) return [];
  const cleaned = rawSources.map((item) => {
    if (!item) return "";
    let title = "";
    if (typeof item === "string") {
      title = item;
    } else if (typeof item === "object") {
      title = item.title || item.name || item.filename || item.file_name || item.source || "";
    }
    return sanitizeSourceTitle(title);
  }).filter(Boolean);
  return Array.from(new Set(cleaned));
}

function sanitizeSourceTitle(title: string) {
  if (!title) return "";
  let cleaned = String(title).trim();
  cleaned = cleaned
    .replace(/\[(BẢNG|TABLE|CONTEXT)\s*\d+\]/gi, "")
    .replace(/\[[^\]]*\]/g, "")
    .replace(/\(\s*Nguồn:\s*/gi, "")
    .replace(/\)\s*$/g, "")
    .replace(/^\s*Nguồn:\s*/gi, "")
    .replace(/^\s*Nguon:\s*/gi, "")
    .replace(/\s+/g, " ")
    .trim().replace(/^,\s*/, "").replace(/,\s*$/, "").trim();
  if (!cleaned) return "";
  const badValues = new Set(["bảng", "context", "table", "nguồn", "nguon", "không rõ nguồn"]);
  if (badValues.has(cleaned.toLowerCase())) return "";
  return cleaned;
}

function MD({ content }: { content: string }) {
  const normalized = useMemo(() => normalizeBotMarkdown(content || ""), [content]);

  if (!normalized) return null;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || "");
          const lang = match?.[1] || "";
          const code = String(children).replace(/\n$/, "");

          if (!inline && lang) {
            return (
              <div className="my-4 rounded-xl overflow-hidden border border-slate-200 shadow-sm">
                <div className="flex items-center justify-between px-4 py-2 bg-slate-100 border-b border-slate-200">
                  <span className="text-xs text-slate-600 font-mono font-medium">{lang}</span>
                  <CopyBtn text={code} />
                </div>
                <SHL
                  style={oneDark}
                  language={lang}
                  PreTag="div"
                  customStyle={{ margin: 0, background: "#1e293b", fontSize: "0.85rem", lineHeight: "1.6", padding: "1rem" }}
                  {...props}
                >
                  {code}
                </SHL>
              </div>
            );
          }
          return (
            <code className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100 text-[0.85em] font-mono">
              {children}
            </code>
          );
        },
        img({ src, alt }: any) {
          return <Img src={src || ""} alt={alt || "Hình minh họa"} userImage={false} />;
        },
        table: ({ children }) => (
          <div className="overflow-x-auto rounded-xl border border-slate-200 my-4 shadow-sm">
            <table className="w-full text-sm text-left">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50 text-slate-700 border-b border-slate-200">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-4 py-3 font-semibold text-slate-800 align-top">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-4 py-3 border-t border-slate-100 text-slate-700 align-top whitespace-pre-wrap break-words">
            {children}
          </td>
        ),
        h1: ({ children }) => <h1 className="text-xl font-bold text-blue-800 mt-6 mb-3">{children}</h1>,
        h2: ({ children }) => <h2 className="text-lg font-bold text-blue-700 mt-5 mb-2">{children}</h2>,
        h3: ({ children }) => <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc list-outside ml-5 space-y-1.5 my-3 text-slate-700">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-outside ml-5 space-y-1.5 my-3 text-slate-700">{children}</ol>,
        li: ({ children }) => <li className="pl-1">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-blue-400 pl-4 py-1 my-4 italic text-slate-600 bg-sky-50 rounded-r-lg">
            {children}
          </blockquote>
        ),
        p: ({ children }) => (
          <p className="my-2 leading-relaxed text-slate-700 whitespace-pre-wrap break-words">
            {children}
          </p>
        ),
        strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
        em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
        hr: () => <hr className="border-slate-200 my-5" />,
        a: ({ href, children }) => (
          <a
            href={href} target="_blank" rel="noopener noreferrer"
            className="text-blue-600 font-medium hover:text-blue-800 underline underline-offset-2 transition-colors"
          >
            {children}
          </a>
        ),
      }}
    >
      {normalized}
    </ReactMarkdown>
  );
}

// CÁC HÀM KIỂM TRA & LỌC TEXT (Giữ nguyên gốc)
function isSeparatorRow(line: string) { return /^\|?[:\-|]+\|?$/.test(line.replace(/\s/g, "")); }
function countPipes(line: string) { return (line.match(/\|/g) || []).length; }
function looksLikeBrokenTableBlock(lines: string[], startIndex: number) {
  const first = lines[startIndex] || ""; const second = lines[startIndex + 1] || "";
  if (!first.trim().startsWith("|") || !second.trim().startsWith("|") || !isSeparatorRow(second)) return false;
  if (first.length > 300 || second.length > 300) return true;
  const hp = countPipes(first); const sp = countPipes(second);
  if (hp < 2 || sp < 2 || Math.abs(hp - sp) > 2) return true;
  for (let i = startIndex + 2; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || !line.trim().startsWith("|")) break;
    if (line.length > 500) return true;
    const p = countPipes(line);
    if (p < 2 || p > hp + 4) return true;
  }
  return false;
}
function isNoiseLine(line: string) {
  const t = line.toLowerCase().trim();
  return (!t || /\[context\s*\d+\]/i.test(line) || /\[bảng\s*\d+\]/i.test(line) || /\[table\s*\d+\]/i.test(line) || /^\(?\s*nguồn\s*:/i.test(t) || /^\(?\s*nguon\s*:/i.test(t) || /^\(\s*nguồn\s*:\s*.*\)\s*$/i.test(t) || /^\(\s*nguon\s*:\s*.*\)\s*$/i.test(t) || t === "(nguồn:)" || t === "(nguon:)" || t === "nguồn:" || t === "nguon:" || t.startsWith("dựa trên tài liệu") || t.startsWith("dựa trên context") || t.startsWith("theo context") || t.startsWith("theo tài liệu [context"));
}
function isMeaninglessRow(text: string) {
  const t = text.toLowerCase().replace(/[*_`\[\]]/g, "").replace(/\s+/g, " ").trim();
  const badRows = ["yêu cầu — chi tiết", "nội dung — chi tiết", "tiêu chí — chi tiết", "chi tiết — nội dung", "nội dung đánh giá — điểm tối đa — các tiêu chí cụ thể", "cách đạt chuẩn đầu ra công nghệ thông tin — chi tiết", "yêu cầu để đạt chuẩn đầu ra công nghệ thông tin — chi tiết", "điều kiện để được miễn thi — nội dung cụ thể"];
  return badRows.includes(t);
}
function convertBrokenTable(lines: string[], startIndex: number) {
  const out: string[] = []; let i = startIndex;
  while (i < lines.length) {
    const current = lines[i] || "";
    if (!current.trim()) { i++; break; }
    if (!current.trim().startsWith("|")) break;
    let cleaned = current.trim();
    if (cleaned.startsWith("|")) cleaned = cleaned.slice(1);
    if (cleaned.endsWith("|")) cleaned = cleaned.slice(0, -1);
    if (/^[:\-|]+$/.test(cleaned.replace(/\s/g, ""))) { i++; continue; }
    const parts = cleaned.split("|").map((part) => sanitizeInline(part)).filter(Boolean);
    if (parts.length >= 2) {
      const left = parts[0]; const right = parts.slice(1).join(" ").trim();
      const rowText = `${left} — ${right}`.trim();
      if (!isMeaninglessRow(rowText) && !isNoiseLine(rowText)) {
        out.push(`- **${left}**`);
        if (right) out.push(`  - ${right}`);
      }
    } else if (parts.length === 1) {
      const rowText = parts[0].trim();
      if (!isMeaninglessRow(rowText) && !isNoiseLine(rowText)) out.push(`- ${rowText}`);
    }
    i++;
  }
  return { out, nextIndex: i };
}
function sanitizeInline(text: string) {
  return text.replace(/\[DONE\]/g, "").replace(/\[CONTENT\]/g, "").replace(/\[CONTEXT\s*\d+\]/gi, "").replace(/\[BẢNG\s*\d+\]/gi, "").replace(/\[TABLE\s*\d+\]/gi, "").replace(/^\s*\(?\s*Nguồn\s*:[^\n]*\)?\s*$/gim, "").replace(/^\s*\(?\s*Nguon\s*:[^\n]*\)?\s*$/gim, "").replace(/<br\s*\/?>/gi, "\n- ").replace(/\s+/g, " ").trim();
}
function normalizeBrokenMarkdownTables(text: string) {
  const lines = text.split("\n"); const out: string[] = []; let i = 0;
  while (i < lines.length) {
    const line = lines[i] || ""; const next = lines[i + 1] || "";
    if (!(line.trim().startsWith("|") && next.trim().startsWith("|") && isSeparatorRow(next))) {
      out.push(line); i++; continue;
    }
    if (!looksLikeBrokenTableBlock(lines, i)) { out.push(line); i++; continue; }
    const converted = convertBrokenTable(lines, i);
    out.push(...converted.out); i = converted.nextIndex;
  }
  return out.join("\n");
}
function convertDashRowsToMarkdown(text: string) {
  const lines = text.split("\n"); const out: string[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { out.push(""); continue; }
    if (isNoiseLine(line)) continue;
    const cleaned = line.replace(/^\d+\.\s*/, "").trim();
    if (cleaned.includes(" — ")) {
      const [left, ...rest] = cleaned.split(" — ");
      const title = left.trim(); const detail = rest.join(" — ").trim();
      if (title) out.push(`- **${title}**`);
      if (detail) {
        detail.replace(/<br\s*\/?>/gi, "\n- ").split("\n").map(x => x.trim()).filter(Boolean).forEach(d => {
          const normalized = d.replace(/^-+\s*/, "").trim();
          if (normalized) out.push(`  - ${normalized}`);
        });
      }
      continue;
    }
    out.push(cleaned);
  }
  return out.join("\n");
}
function dedupeLines(text: string) {
  const lines = text.split("\n"); const out: string[] = []; const seen = new Set<string>();
  for (const raw of lines) {
    const line = raw.trimRight(); const key = line.trim().toLowerCase().replace(/\s+/g, " ");
    if (!key) { if (out.length > 0 && out[out.length - 1] !== "") out.push(""); continue; }
    if (seen.has(key)) continue;
    seen.add(key); out.push(line);
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
function normalizeBotMarkdown(text: string) {
  if (!text) return "";
  
  // Dọn dẹp các mã code rác sinh ra từ API nếu có
  let cleaned = text.replace(/\r\n/g, "\n")
    .replace(/\[DONE\]/g, "")
    .replace(/\[CONTENT\]/g, "")
    .replace(/\[CONTEXT\s*\d+\]/gi, "")
    .replace(/\[BẢNG\s*\d+\]/gi, "")
    .replace(/\[TABLE\s*\d+\]/gi, "")
    .replace(/^\s*\(?\s*Nguồn\s*:[^\n]*\)?\s*$/gim, "")
    .replace(/^\s*\(?\s*Nguon\s*:[^\n]*\)?\s*$/gim, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/[ \t]+\n/g, "\n");

  cleaned = normalizeBrokenMarkdownTables(cleaned);
  cleaned = convertDashRowsToMarkdown(cleaned);

  // ĐÃ SỬA LỖI CẮT CHỮ: Bỏ hoàn toàn việc lọc isNoiseLine và dedupeLines 
  // vì nó chính là nguyên nhân xóa nhầm các đoạn chữ đang stream từ bot.
  return cleaned.trim();
}

// ==========================================
// CÁC COMPONENT PHỤ TRỢ
// ==========================================

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="text-xs text-slate-500 hover:text-blue-600 font-medium transition-colors bg-white px-2 py-1 rounded shadow-sm border border-slate-200"
    >
      {copied ? "✓ Đã copy" : "Copy"}
    </button>
  );
}

function Img({ src, alt, userImage = false }: { src: string; alt: string; userImage?: boolean }) {
  const [err, setErr] = useState(false);
  const [loaded, setLoaded] = useState(false);

  if (err) {
    return (
      <div className="my-3 rounded-2xl border border-red-100 bg-red-50 p-6 text-center">
        <div className="text-2xl mb-2 opacity-50">🖼️</div>
        <p className="text-xs text-red-400 italic">Không thể tải ảnh: {alt}</p>
      </div>
    );
  }

  return (
    <figure className="my-3 relative">
      {!loaded && (
        <div className="rounded-2xl bg-slate-100 border border-slate-200 animate-pulse w-full" style={{ height: "200px" }} />
      )}
      <img
        src={src}
        alt={alt}
        onError={() => setErr(true)}
        onLoad={() => setLoaded(true)}
        loading="lazy"
        className={clsx(
          "rounded-2xl w-full border border-slate-200 transition-opacity duration-300 shadow-sm",
          loaded ? "opacity-100" : "opacity-0 absolute top-0 left-0",
          userImage ? "object-contain bg-white" : "object-cover"
        )}
        style={{ maxHeight: "400px" }}
      />
      {alt && loaded && !userImage && (
        <figcaption className="text-xs text-slate-400 text-center mt-2 italic font-medium">
          {alt}
        </figcaption>
      )}
    </figure>
  );
}