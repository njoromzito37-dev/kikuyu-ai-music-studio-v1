import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kikuyu AI Music Studio",
  description: "AI music generation for Gĩkũyũ and Kenyan musical genres.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
