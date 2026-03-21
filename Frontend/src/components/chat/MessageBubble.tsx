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
  const sources = msg.sources ?? [];

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
        "flex gap-3 animate-fade-up",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <div
        className={clsx(
          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold",
          isUser
            ? "bg-accent text-surface-DEFAULT"
            : "bg-surface-2 border border-surface-3 text-base"
        )}
      >
        {isUser ? "SV" : "🤖"}
      </div>

      <div className="max-w-[82%] space-y-1.5">
        <div
          className={clsx(
            "rounded-2xl px-4 py-3 text-sm",
            isUser
              ? "bg-accent/10 border border-accent/20 text-text-primary rounded-tr-sm"
              : "bg-surface-1 border border-surface-3 text-text-primary rounded-tl-sm"
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
                  <div className="flex items-center gap-1.5 text-xs text-text-muted">
                    <ImageIcon className="w-3.5 h-3.5 text-accent" />
                    <span>Ảnh bạn đã gửi</span>
                  </div>
                  <div className="grid gap-3">
                    {imageUrls.map((url, idx) => (
                      <Img key={`${url}-${idx}`} src={url} alt={`Ảnh đã gửi ${idx + 1}`} userImage />
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
                  <div className="flex items-center gap-1.5 text-xs text-text-muted">
                    <ImageIcon className="w-3.5 h-3.5 text-accent" />
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
                <span className="inline-block w-2 h-4 bg-accent animate-pulse ml-0.5 rounded-sm align-text-bottom" />
              )}
            </div>
          )}
        </div>

        {!isUser && sources.length > 0 && (
          <div className="flex items-start gap-1.5 px-2">
            <BookOpen className="w-3 h-3 text-accent flex-shrink-0 mt-0.5" />
            <p className="text-xs text-text-muted">
              <span className="text-accent font-medium">Nguồn: </span>
              {sources.map((s, i) => (
                <span key={i}>
                  <span className="italic text-text-secondary">{s}</span>
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

function MD({ content }: { content: string }) {
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
              <div className="my-3 rounded-xl overflow-hidden border border-surface-3">
                <div className="flex items-center justify-between px-4 py-1.5 bg-surface-3">
                  <span className="text-xs text-text-secondary font-mono">{lang}</span>
                  <CopyBtn text={code} />
                </div>
                <SHL
                  style={oneDark}
                  language={lang}
                  PreTag="div"
                  customStyle={{
                    margin: 0,
                    background: "#0d1117",
                    fontSize: "0.82rem",
                    lineHeight: "1.6",
                  }}
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

        img({ src, alt }: any) {
          return <Img src={src || ""} alt={alt || "Hình minh họa"} userImage={false} />;
        },

        table: ({ children }) => (
          <div className="overflow-x-auto rounded-xl border border-surface-3 my-3">
            <table className="w-full text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-surface-3 text-text-secondary">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left font-medium uppercase tracking-wide text-xs">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 border-t border-surface-3 text-text-primary">
            {children}
          </td>
        ),
        h1: ({ children }) => (
          <h1 className="text-xl font-bold text-text-primary mt-5 mb-2">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-lg font-bold text-accent mt-4 mb-2 border-b border-surface-3 pb-1">
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-base font-semibold text-text-primary mt-3 mb-1">
            {children}
          </h3>
        ),
        ul: ({ children }) => (
          <ul className="list-disc list-inside space-y-1 my-2 text-text-primary">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal list-inside space-y-1 my-2 text-text-primary">
            {children}
          </ol>
        ),
        li: ({ children }) => <li className="ml-2">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-accent pl-4 py-1 my-3 italic text-text-secondary bg-surface-2 rounded-r-lg">
            {children}
          </blockquote>
        ),
        p: ({ children }) => (
          <p className="my-1.5 leading-relaxed text-text-primary">{children}</p>
        ),
        strong: ({ children }) => (
          <strong className="font-bold text-accent">{children}</strong>
        ),
        em: ({ children }) => (
          <em className="italic text-text-secondary">{children}</em>
        ),
        hr: () => <hr className="border-surface-3 my-4" />,
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline underline-offset-2 hover:text-accent-dim transition-colors"
          >
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

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

function Img({
  src,
  alt,
  userImage = false,
}: {
  src: string;
  alt: string;
  userImage?: boolean;
}) {
  const [err, setErr] = useState(false);
  const [loaded, setLoaded] = useState(false);

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
      {!loaded && (
        <div
          className="rounded-2xl bg-surface-2 border border-surface-3 animate-pulse"
          style={{ height: "240px" }}
        />
      )}

      <img
        src={src}
        alt={alt}
        onError={() => setErr(true)}
        onLoad={() => setLoaded(true)}
        loading="lazy"
        className={clsx(
          "rounded-2xl w-full border border-surface-3 transition-opacity duration-300",
          loaded ? "opacity-100" : "opacity-0 absolute",
          userImage ? "object-contain bg-surface-2" : "object-cover"
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