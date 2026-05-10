"use client";

import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { getAuthStatus, login as apiLogin, register as apiRegister, logout as apiLogout, type AuthStatus } from "@/lib/auth-api";

interface AuthState {
  status: AuthStatus | null;
  loading: boolean;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  login: (username: string, password: string) => Promise<boolean>;
  register: (username: string, password: string) => Promise<{ ok: boolean; detail?: string }>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  isAuthenticated: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: null, loading: true, error: null });
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const status = await getAuthStatus();
      if (mountedRef.current) {
        setState({ status, loading: false, error: null });
      }
    } catch {
      if (mountedRef.current) {
        setState({ status: null, loading: false, error: "Failed to check auth status" });
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    refresh();
    return () => { mountedRef.current = false; };
  }, [refresh]);

  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    const result = await apiLogin(username, password);
    if (result.ok) {
      await refresh();
      return true;
    }
    setState(prev => ({ ...prev, loading: false, error: result.detail || "Login failed" }));
    return false;
  }, [refresh]);

  const register = useCallback(async (username: string, password: string): Promise<{ ok: boolean; detail?: string }> => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    const result = await apiRegister(username, password);
    if (result.ok) {
      await refresh();
      return { ok: true };
    }
    setState(prev => ({ ...prev, loading: false, error: result.detail || "Registration failed" }));
    return result;
  }, [refresh]);

  const logout = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true }));
    await apiLogout();
    await refresh();
    if (typeof window !== "undefined") {
      window.location.href = "/";
    }
  }, [refresh]);

  const value: AuthContextValue = {
    ...state,
    login,
    register,
    logout,
    refresh,
    isAuthenticated: state.status?.authenticated ?? false,
    isAdmin: state.status?.is_admin ?? false,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
