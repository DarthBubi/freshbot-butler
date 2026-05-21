import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Freshbot Butler",
  description: "Gemeinsamer Küchenüberblick für deinen Haushalt"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
