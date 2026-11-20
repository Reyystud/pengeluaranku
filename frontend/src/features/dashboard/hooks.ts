import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { CategorySplit, Merchants, RangeName, Summary, Trends } from "@/api/types";

// Every dashboard query lives under ["analytics", ...] so a transaction write can refresh them all.
export function useSummary(range: RangeName) {
  return useQuery({
    queryKey: ["analytics", "summary", range],
    queryFn: ({ signal }) => api.get<Summary>("/analytics/summary", { range }, signal),
  });
}

export function useCategorySplit(range: RangeName) {
  return useQuery({
    queryKey: ["analytics", "categories", range],
    queryFn: ({ signal }) => api.get<CategorySplit>("/analytics/categories", { range }, signal),
  });
}

export function useTrend(range: RangeName) {
  return useQuery({
    queryKey: ["analytics", "trends", range],
    queryFn: ({ signal }) => api.get<Trends>("/analytics/trends", { range }, signal),
  });
}

export function useMerchants(range: RangeName) {
  return useQuery({
    queryKey: ["analytics", "merchants", range],
    queryFn: ({ signal }) =>
      api.get<Merchants>("/analytics/merchants", { range, limit: 5 }, signal),
  });
}
