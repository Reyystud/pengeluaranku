import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  CategorizePreviewOut,
  Category,
  Transaction,
  TransactionCreated,
  TransactionPage,
  TransactionType,
  TransactionUpdated,
} from "@/api/types";

export interface Filters {
  q: string;
  type: "" | TransactionType;
  category: string;
  from: string;
  to: string;
  review: boolean;
}

export const EMPTY_FILTERS: Filters = {
  q: "",
  type: "",
  category: "",
  from: "",
  to: "",
  review: false,
};

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/categories"),
    staleTime: Infinity,
  });
}

export function useTransactions(filters: Filters) {
  return useInfiniteQuery({
    queryKey: ["transactions", filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.get<TransactionPage>(
        "/transactions",
        {
          q: filters.q,
          transaction_type: filters.type,
          category: filters.category ? [filters.category] : undefined,
          date_from: filters.from,
          date_to: filters.to,
          category_status: filters.review ? "needs_review" : undefined,
          limit: 25,
          cursor: pageParam,
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
}

/** Number of rows waiting for review, for the tab badge. */
export function useReviewCount() {
  return useQuery({
    queryKey: ["transactions", "review-count"],
    queryFn: () =>
      api.get<{ count: number }>("/transactions/count", { category_status: "needs_review" }),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["transactions"] });
}

export interface TransactionInput {
  transaction_type: TransactionType;
  amount: string;
  description: string;
  merchant?: string | null;
  transaction_date: string;
  payment_method: string;
  category?: string | null;
  notes?: string | null;
}

export function useCreateTransaction() {
  const invalidate = useInvalidate();
  return useMutation({
    // The backend requires Idempotency-Key (PRD 13.1.4). The caller owns the key so that a
    // double click or a network retry of the same form replays instead of creating twice.
    mutationFn: ({ body, key }: { body: TransactionInput; key: string }) =>
      api.post<TransactionCreated>("/transactions", body, { headers: { "Idempotency-Key": key } }),
    onSuccess: invalidate,
  });
}

export function useUpdateTransaction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<TransactionUpdated>(`/transactions/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useDeleteTransactions() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids: string[]) =>
      api.post<{ deleted: number }>(
        "/transactions/bulk-delete",
        { ids },
        { headers: { "Idempotency-Key": crypto.randomUUID() } }, // required by the API (13.1.4)
      ),
    onSuccess: invalidate,
  });
}

export function useConfirmCategory() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<Transaction>(`/transactions/${id}/confirm-category`),
    onSuccess: invalidate,
  });
}

export function useDismissDuplicate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<Transaction>(`/transactions/${id}/dismiss-duplicate`),
    onSuccess: invalidate,
  });
}

export function usePreviewCategory() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<CategorizePreviewOut>("/transactions/categorize-preview", body),
  });
}
