import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { t } from "@/lib/i18n";

export const metadata: Metadata = {
  title: { default: t("app.name"), template: `%s · ${t("app.short")}` },
  description: t("landing.body"),
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
