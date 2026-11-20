import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  Anomaly,
  AnomalyPage,
  AnomalySeverity,
  AnomalyStatus,
  AnomalyType,
  DismissReason,
} from "@/api/types";

export interface AnomalyFilters {
  status: AnomalyStatus | "";
  severity: AnomalySeverity | "";
  type: AnomalyType | "";
}

export const NO_FILTERS: AnomalyFilters = { status: "", severity: "", type: "" };

export function useAnomalies(filters: AnomalyFilters) {
  return useInfiniteQuery({
    queryKey: ["anomalies", "list", filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.get<AnomalyPage>(
        "/intelligence/anomalies",
        {
          status: filters.status || undefined,
          severity: filters.severity || undefined,
          type: filters.type || undefined,
          limit: 20,
          cursor: pageParam,
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
}

/** The dashboard card: open anomalies that raised an alert. */
export function useActiveAlerts(limit = 3) {
  return useQuery({
    queryKey: ["anomalies", "alerts", limit],
    queryFn: ({ signal }) =>
      api.get<AnomalyPage>(
        "/intelligence/anomalies",
        { status: "open", alerts_only: true, limit },
        signal,
      ),
  });
}

export function useAnomalyFeedback() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; action: "confirm" | "dismiss"; reason?: DismissReason }) =>
      api.post<Anomaly>(`/intelligence/anomalies/${v.id}/feedback`, {
        action: v.action,
        reason: v.reason,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["anomalies"] }),
  });
}
