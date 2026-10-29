"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import {
  clearToken,
  getToken,
  login as apiLogin,
  me,
  register as apiRegister,
  setToken,
} from "./api";
import type { User } from "./types";

/** 登录页本身不需要登录态 */
const isPublicPath = (p: string) => p === "/login" || p.startsWith("/login/");

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signUp: (email: string, password: string, displayName: string) => Promise<User>;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const pathname = usePathname() || "/";

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await me());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /**
   * 路由守卫（客户端）：静态导出下没有 middleware，改在这里做。
   * 未登录访问受保护页面直接跳登录，并带上回跳地址。
   */
  useEffect(() => {
    if (loading || isPublicPath(pathname)) return;
    if (!getToken()) {
      const back = pathname + (typeof window !== "undefined" ? window.location.search : "");
      window.location.replace(`/login?next=${encodeURIComponent(back)}`);
    }
  }, [loading, pathname]);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const signUp = useCallback(async (email: string, password: string, displayName: string) => {
    const res = await apiRegister(email, password, displayName);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
    window.location.href = "/login";
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut, refresh }),
    [user, loading, signIn, signUp, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
