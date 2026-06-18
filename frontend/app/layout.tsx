import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "ReelMagic — one-tap trip reels",
  description:
    "Drop your trip photos and clips, pick a vibe, and get a finished beat-synced vertical reel. Zero manual editing.",
};

export const viewport: Viewport = {
  themeColor: "#0b0b12",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Runtime-configurable API base: set API_BASE (server env) on the host and the
  // same built image points at any backend — no rebuild needed.
  const runtimeApiBase = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "";
  return (
    <html lang="en">
      <head>
        {runtimeApiBase ? (
          <script
            dangerouslySetInnerHTML={{
              __html: `window.__API_BASE__=${JSON.stringify(runtimeApiBase)};`,
            }}
          />
        ) : null}
      </head>
      <body>
        <header className="mx-auto flex max-w-5xl items-center justify-between px-5 py-5">
          <Link href="/" className="text-xl font-extrabold tracking-tight">
            <span className="brand-gradient">Reel</span>
            <span className="text-white">Magic</span>
          </Link>
          <span className="text-xs text-white/40">friends-trip reels, automatically</span>
        </header>
        <main className="mx-auto max-w-5xl px-5 pb-24">{children}</main>
      </body>
    </html>
  );
}
