import type { Metadata } from "next";
import { Archivo } from "next/font/google";
import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "CG/lab AutoAgent",
  description: "Busca conversacional de veículos com agente, RAG e guardrails",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className={archivo.variable}>{children}</body>
    </html>
  );
}
