"use client";
import { useState } from "react";
import { Message } from "@/lib/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SHL } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { BookOpen } from "lucide-react";
import clsx from "clsx";

export default function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div className={clsx("flex gap-3 animate-fade-up", isUser ? "flex-row-reverse" : "flex-row")}>
      <div className={clsx(
        "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold",
        isUser ? "bg-accent text-surface-DEFAULT" : "bg-surface-2 border border-surface-3 text-base"
      )}>
        {isUser ? "SV" : "🤖"}
      </div>

      <div className="max-w-[82%] space-y-1.5">
        <div className={clsx(
          "rounded-2xl px-4 py-3 text-sm",
          isUser
            ? "bg-accent/10 border border-accent/20 text-text-primary rounded-tr-sm"
            : "bg-surface-1 border border-surface-3 text-text-primary rounded-tl-sm"
        )}>
          {isUser
            ? <p className="leading-relaxed whitespace-pre-wrap break-words">{msg.content}</p>
            : (
              <div>
                <MD content={msg.content} />
                {msg.isStreaming && (
                  <span className="inline-block w-2 h-4 bg-accent animate-pulse ml-0.5 rounded-sm align-text-bottom" />
                )}
              </div>
            )
          }
        </div>

        {/* Citation sources */}
        {msg.sources && msg.sources.length > 0 && (
          <div className="flex items-start gap-1.5 px-2">
            <BookOpen className="w-3 h-3 text-accent flex-shrink-0 mt-0.5" />
            <p className="text-xs text-text-muted">
              <span className="text-accent font-medium">Nguồn: </span>
              {msg.sources.map((s, i) => (
                <span key={i}>
                  <span className="italic text-text-secondary">{s}</span>
                  {i < msg.sources!.length - 1 && ", "}
                </span>
              ))}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Markdown renderer ─────────────────────────────────────────
function MD({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Code block với syntax highlighting
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        code({ inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || "");
          const lang = match?.[1] || "";
          const code = String(children).replace(/\n$/, "");

          if (!inline && lang) {
            return (
              <div className="my-3 rounded-xl overflow-hidden border border-surface-3">
                <div className="flex items-center justify-between px-4 py-1.5 bg-surface-3">
                  <span className="text-xs text-text-secondary font-mono">{lang}</span>
                  <CopyBtn text={code} />
                </div>
                <SHL
                  style={oneDark}
                  language={lang}
                  PreTag="div"
                  customStyle={{ margin: 0, background: "#0d1117", fontSize: "0.82rem", lineHeight: "1.6" }}
                  {...props}
                >
                  {code}
                </SHL>
              </div>
            );
          }
          return (
            <code className="px-1.5 py-0.5 rounded bg-surface-3 text-accent text-xs font-mono">
              {children}
            </code>
          );
        },

        // Hình ảnh — dùng thẳng <img> không qua Next.js Image
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        img({ src, alt }: any) {
          return <Img src={src || ""} alt={alt || "Hình minh họa"} />;
        },

        // Bảng
        table: ({ children }) => (
          <div className="overflow-x-auto rounded-xl border border-surface-3 my-3">
            <table className="w-full text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-surface-3 text-text-secondary">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left font-medium uppercase tracking-wide text-xs">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 border-t border-surface-3 text-text-primary">{children}</td>
        ),

        // Headings
        h1: ({ children }) => <h1 className="text-xl font-bold text-text-primary mt-5 mb-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-lg font-bold text-accent mt-4 mb-2 border-b border-surface-3 pb-1">{children}</h2>,
        h3: ({ children }) => <h3 className="text-base font-semibold text-text-primary mt-3 mb-1">{children}</h3>,

        // Lists
        ul: ({ children }) => <ul className="list-disc list-inside space-y-1 my-2 text-text-primary">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 my-2 text-text-primary">{children}</ol>,
        li: ({ children }) => <li className="ml-2">{children}</li>,

        // Blockquote
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-accent pl-4 py-1 my-3 italic text-text-secondary bg-surface-2 rounded-r-lg">
            {children}
          </blockquote>
        ),

        // Paragraph
        p: ({ children }) => <p className="my-1.5 leading-relaxed text-text-primary">{children}</p>,

        // Inline styles
        strong: ({ children }) => <strong className="font-bold text-accent">{children}</strong>,
        em: ({ children }) => <em className="italic text-text-secondary">{children}</em>,
        hr: () => <hr className="border-surface-3 my-4" />,

        // Link
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer"
            className="text-accent underline underline-offset-2 hover:text-accent-dim transition-colors">
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ── Copy button ───────────────────────────────────────────────
function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="text-xs text-text-secondary hover:text-accent transition-colors"
    >
      {copied ? "✓ Copied" : "Copy"}
    </button>
  );
}

// ── Image với fallback và nhiều nguồn ảnh ────────────────────
function Img({ src, alt }: { src: string; alt: string }) {
  const [err, setErr] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // Nếu Unsplash source lỗi, thử fallback sang Picsum
  const fallbackSrc = src.includes("unsplash.com")
    ? `https://picsum.photos/seed/${encodeURIComponent(alt)}/800/450`
    : src.includes("picsum.photos")
    ? `https://placehold.co/800x450/1e2535/6ee7b7?text=${encodeURIComponent(alt)}`
    : `https://placehold.co/800x450/1e2535/6ee7b7?text=${encodeURIComponent(alt)}`;

  const [currentSrc, setCurrentSrc] = useState(src);

  const handleError = () => {
    if (currentSrc === src) {
      // Thử fallback lần 1
      setCurrentSrc(fallbackSrc);
    } else {
      // Fallback lần 2 — hiện placeholder text
      setErr(true);
    }
  };

  if (err) {
    return (
      <div className="my-4 rounded-2xl border border-surface-3 bg-surface-2 p-6 text-center">
        <div className="text-3xl mb-2">🖼️</div>
        <p className="text-xs text-text-muted italic">{alt}</p>
      </div>
    );
  }

  return (
    <figure className="my-4">
      {/* Skeleton loader khi ảnh đang load */}
      {!loaded && (
        <div className="rounded-2xl bg-surface-2 border border-surface-3 animate-pulse"
          style={{ height: "240px" }} />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={currentSrc}
        alt={alt}
        onError={handleError}
        onLoad={() => setLoaded(true)}
        loading="lazy"
        crossOrigin="anonymous"
        referrerPolicy="no-referrer"
        className={clsx(
          "rounded-2xl w-full border border-surface-3 object-cover transition-opacity duration-300",
          loaded ? "opacity-100" : "opacity-0 absolute"
        )}
        style={{ maxHeight: "400px" }}
      />
      {alt && loaded && (
        <figcaption className="text-xs text-text-muted text-center mt-1.5 italic">
          {alt}
        </figcaption>
      )}
    </figure>
  );
}