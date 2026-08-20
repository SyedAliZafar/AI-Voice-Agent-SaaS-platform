import { Inter } from "next/font/google";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata = {
  title: "VoiceAgent — build voice agents, wired to Retell",
  description:
    "Design a voice agent, give it a script, and put it on a real phone line. Connected to your Retell account.",
};

/** Root layout owns the document and nothing else. The app chrome (sidebar, topbar)
 * lives in `(app)/layout.tsx` so the marketing pages at `/` can render full-bleed
 * without it. Both route groups share this html/body and the font. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen font-sans text-slate-900 antialiased">{children}</body>
    </html>
  );
}
