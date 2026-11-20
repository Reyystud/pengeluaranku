import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ForecastResponse } from "@/api/types";

/** FR-07: the latest forecast for the overall spending or one expense category. */
export function useForecast(category: string) {
  return useQuery({
    queryKey: ["forecast", category],
    queryFn: ({ signal }) =>
      api.get<ForecastResponse>(
        "/intelligence/forecast",
        { category: category || undefined },
        signal,
      ),
  });
}
