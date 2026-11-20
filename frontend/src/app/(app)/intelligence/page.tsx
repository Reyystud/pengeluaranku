import type { Metadata } from "next";
import { AnomaliesView } from "@/features/intelligence/AnomaliesView";

export const metadata: Metadata = { title: "Intelligence" };
export default function Page() {
  return <AnomaliesView />;
}
