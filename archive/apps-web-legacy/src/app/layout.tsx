import type { Metadata } from "next";
import Link from "next/link";
import { JetBrains_Mono, Outfit } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";
import { SessionProvider } from "@/shared/session/provider";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap"
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap"
});

export const metadata: Metadata = {
  title: "Northline Agent Console",
  description: "Crea agentes empresariales, indexa conocimiento y conversa con RAG en minutos.",
  openGraph: {
    title: "Northline Agent Console",
    description: "Registro, onboarding, agentes, RAG y chat desde un dashboard unico.",
    images: [{ url: "https://picsum.photos/seed/northline-og/1200/630" }]
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="es">
      <body className={`${outfit.variable} ${jetBrainsMono.variable}`}>
        <a href="#main-content" className="skip-link">
          Saltar al contenido principal
        </a>
        <SessionProvider>
          <main id="main-content" className="app-main">
            {children}
          </main>
          <footer className="app-footer">
            <div className="app-footer-inner">
              <p>Northline Agent Console</p>
              <nav aria-label="Legal">
                <Link href="/privacy">Privacy policy</Link>
                <Link href="/terms">Terms of service</Link>
              </nav>
            </div>
          </footer>
        </SessionProvider>
      </body>
    </html>
  );
}
