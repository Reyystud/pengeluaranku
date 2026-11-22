import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { SegmentResponse } from "@/api/types";

/** FR-13.04: the user's behavior segment and its defining traits (Intelligence Center only). */
export function useSegment() {
  return useQuery({
    queryKey: ["segment"],
    queryFn: ({ signal }) => api.get<SegmentResponse>("/intelligence/segment", undefined, signal),
  });
}
