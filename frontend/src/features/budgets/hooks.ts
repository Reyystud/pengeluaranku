import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Budget, BudgetHistory, BudgetList } from "@/api/types";

export function useBudgets() {
  return useQuery({
    queryKey: ["budgets"],
    queryFn: ({ signal }) => api.get<BudgetList>("/budgets", undefined, signal),
  });
}

export function useBudgetHistory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["budgets", id, "history"],
    queryFn: ({ signal }) =>
      api.get<BudgetHistory>(`/budgets/${id}/history`, { limit: 12 }, signal),
    enabled,
  });
}

function useRefresh() {
  const client = useQueryClient();
  // A budget change can create a notification (threshold already crossed).
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["budgets"] }),
      client.invalidateQueries({ queryKey: ["notifications"] }),
    ]);
}

export interface BudgetInput {
  category?: string | null;
  limit_amount: string;
  alert_thresholds?: number[];
}

export function useCreateBudget() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: BudgetInput) => api.post<Budget>("/budgets", body),
    onSuccess: refresh,
  });
}

export function useUpdateBudget() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<BudgetInput> }) =>
      api.patch<Budget>(`/budgets/${id}`, body),
    onSuccess: refresh,
  });
}

export function useDeleteBudget() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/budgets/${id}`),
    onSuccess: refresh,
  });
}
