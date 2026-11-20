import type { Metadata } from "next";
import { IntelligenceView } from "@/features/intelligence/IntelligenceView";

export const metadata: Metadata = { title: "Intelligence" };
export default function Page() {
  return <IntelligenceView />;
}
