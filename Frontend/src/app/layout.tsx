import type { Metadata } from "next";
import { Sora, JetBrains_Mono } from "next/font/google";
import "./globals.css";
const sora = Sora({ subsets:["latin"], variable:"--font-body", display:"swap" });
const mono = JetBrains_Mono({ subsets:["latin"], variable:"--font-mono", display:"swap" });
export const metadata: Metadata = {
  title: "NCKH StudyBot — Trợ lý nghiên cứu AI",
  description: "Chatbot AI hỗ trợ nghiên cứu khoa học sinh viên — RAG + Voice + Hình ảnh",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className={`${sora.variable} ${mono.variable} font-sans bg-surface-DEFAULT text-text-primary antialiased`}>
        {children}
      </body>
    </html>
  );
}