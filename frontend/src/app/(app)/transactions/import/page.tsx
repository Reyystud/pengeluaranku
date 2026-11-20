import type { Metadata } from "next";
import { ImportView } from "@/features/imports/ImportView";

export const metadata: Metadata = { title: "Import CSV" };
export default function Page() {
  return <ImportView />;
}
