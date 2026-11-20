"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { t } from "@/lib/i18n";

/** Right-side drawer on desktop, full screen on phones. Radix handles focus trap and Escape. */
export function Drawer({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-50 flex w-full flex-col overflow-y-auto border-l border-border bg-card p-5 shadow-xl sm:max-w-md motion-safe:animate-[drawer-in_180ms_ease-out]"
        >
          <div className="mb-4 flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Close
              aria-label={t("common.close")}
              className="grid size-11 place-items-center rounded-md hover:bg-muted sm:size-9"
            >
              <X aria-hidden className="size-5" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
