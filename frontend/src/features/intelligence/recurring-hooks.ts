import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { RecurringList, RecurringSeries } from "@/api/types";

/** FR-08: recurring series, sorted by next due date, with monthly totals. */
export function useRecurring() {
  return useQuery({
    queryKey: ["recurring"],
    queryFn: ({ signal }) => api.get<RecurringList>("/intelligence/recurring", undefined, signal),
  });
}

export interface RecurringChange {
  id: string;
  status?: "user_confirmed" | "user_rejected";
  /** `null` clears the user's amount (FR-08.05). */
  user_expected_amount?: string | null;
}

export function useRecurringUpdate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: RecurringChange) =>
      api.patch<RecurringSeries>(`/intelligence/recurring/${id}`, body),
    onSuccess: async () => {
      // totals and the forecast both depend on which series count
      await Promise.all([
        client.invalidateQueries({ queryKey: ["recurring"] }),
        client.invalidateQueries({ queryKey: ["forecast"] }),
      ]);
    },
  });
}
