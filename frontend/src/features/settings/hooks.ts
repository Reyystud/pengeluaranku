import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, request } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import type { Category, MerchantRule, MerchantRuleList, ProfileUpdate, User } from "@/api/types";

/** FR-01: edit the profile; the signed-in user in context is replaced by the server's answer. */
export function useProfileUpdate() {
  const { updateUser } = useAuth();
  return useMutation({
    mutationFn: (body: ProfileUpdate) => api.patch<User>("/users/me", body),
    onSuccess: (user) => updateUser(user),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post<void>("/users/me/password", body),
  });
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: (body: { password: string; confirm: string }) =>
      request<void>("/users/me", { method: "DELETE", json: body }),
  });
}

/** FR-15.01: the user's merchant rules. */
export function useMerchantRules() {
  return useQuery({
    queryKey: ["merchant-rules"],
    queryFn: ({ signal }) => api.get<MerchantRuleList>("/merchant-rules", undefined, signal),
  });
}

export function useRuleCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: ({ signal }) => api.get<Category[]>("/categories", undefined, signal),
    staleTime: Infinity,
  });
}

export function useRuleUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, category }: { id: string; category: string }) =>
      api.patch<MerchantRule>(`/merchant-rules/${id}`, { category }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["merchant-rules"] }),
  });
}

export function useRuleDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/merchant-rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["merchant-rules"] }),
  });
}
