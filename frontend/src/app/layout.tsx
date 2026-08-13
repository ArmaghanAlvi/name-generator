import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Namecraft",
  description: "Discover names through meanings and languages.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-stone-50 text-slate-900 antialiased">
        {children}
      </body>
    </html>
  );
}