import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AppNotification, NotificationPage } from "@/api/types";

/** FR-14.04: poll every 60 s, and only while the tab is visible (no websockets in this release). */
export const POLL_MS = 60_000;

export function useUnreadCount() {
  return useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: ({ signal }) =>
      api.get<{ count: number }>("/notifications/unread-count", undefined, signal),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  });
}

export function useNotifications(unreadOnly: boolean) {
  return useInfiniteQuery({
    queryKey: ["notifications", "list", unreadOnly],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.get<NotificationPage>(
        "/notifications",
        { unread_only: unreadOnly, limit: 20, cursor: pageParam },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
}

function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["notifications"] });
}

export function useMarkRead() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) => api.post<AppNotification>(`/notifications/${id}/read`),
    onSuccess: refresh,
  });
}

export function useMarkAllRead() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: () => api.post<{ updated: number }>("/notifications/read-all"),
    onSuccess: refresh,
  });
}
