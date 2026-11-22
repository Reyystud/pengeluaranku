"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, refreshSession } from "@/api/client";
import type { AuthResponse, User } from "@/api/types";
import { setAuthLostHandler, setToken } from "./token";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthValue {
  status: Status;
  user: User | null;
  timeZone: string;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  updateUser: (user: User) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const router = useRouter();
  const queryClient = useQueryClient();

  const clear = useCallback(() => {
    setToken(null);
    setUser(null);
    setStatus("anonymous");
    queryClient.clear();
  }, [queryClient]);

  // On a fresh page load the in-memory token is gone: the refresh cookie restores the session.
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!(await refreshSession())) {
        if (alive) setStatus("anonymous");
        return;
      }
      try {
        const me = await api.get<User>("/users/me");
        if (alive) {
          setUser(me);
          setStatus("authenticated");
        }
      } catch {
        if (alive) clear();
      }
    })();
    return () => {
      alive = false;
    };
  }, [clear]);

  useEffect(() => {
    setAuthLostHandler(() => {
      clear();
      router.replace("/login");
    });
    return () => setAuthLostHandler(null);
  }, [clear, router]);

  const accept = useCallback((response: AuthResponse) => {
    setToken(response.access_token);
    setUser(response.user);
    setStatus("authenticated");
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      timeZone: user?.timezone ?? "Asia/Jakarta",
      login: async (email, password) => {
        accept(
          await api.post<AuthResponse>("/auth/login", { email, password }, { anonymous: true }),
        );
      },
      register: async (email, password, displayName) => {
        accept(
          await api.post<AuthResponse>(
            "/auth/register",
            { email, password, display_name: displayName },
            { anonymous: true },
          ),
        );
      },
      updateUser: (next) => setUser(next),
      logout: async () => {
        try {
          await api.post("/auth/logout", undefined, { anonymous: true });
        } finally {
          clear();
          router.replace("/login");
        }
      },
    }),
    [status, user, accept, clear, router],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
