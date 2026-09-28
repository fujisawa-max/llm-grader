import "./globals.css";
import "katex/dist/katex.min.css";
import { CurrentUserProvider } from "@/lib/currentUser";
import { AppShell } from "@/components/AppShell";
export const metadata = { title: process.env.NEXT_PUBLIC_APP_NAME || "AI採点支援システム" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ja"><body><CurrentUserProvider><AppShell>{children}</AppShell></CurrentUserProvider></body></html>; }
