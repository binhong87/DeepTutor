import { apiUrl, apiFetch } from "@/lib/api";

export interface AuthStatus {
  enabled: boolean;
  authenticated: boolean;
  user_id: string | null;
  username: string | null;
  role: string | null;
  is_admin: boolean;
}

export interface UserInfo {
  id?: string;
  username: string;
  role: string;
  created_at: string;
  disabled?: boolean;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const res = await apiFetch(apiUrl("/api/v1/auth/status"));
  if (!res.ok) {
    return { enabled: false, authenticated: false, user_id: null, username: null, role: null, is_admin: false };
  }
  return res.json();
}

export async function login(username: string, password: string): Promise<{ ok: boolean; detail?: string }> {
  const res = await apiFetch(apiUrl("/api/v1/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return { ok: false, detail: data.detail || "Login failed" };
  }
  return { ok: true };
}

export async function register(username: string, password: string): Promise<{ ok: boolean; detail?: string }> {
  const res = await apiFetch(apiUrl("/api/v1/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return { ok: false, detail: data.detail || "Registration failed" };
  }
  return { ok: true };
}

export async function logout(): Promise<void> {
  await apiFetch(apiUrl("/api/v1/auth/logout"), { method: "POST" });
}

export async function checkIsFirstUser(): Promise<boolean> {
  const res = await apiFetch(apiUrl("/api/v1/auth/is_first_user"));
  if (!res.ok) return true;
  const data = await res.json();
  return data.is_first_user === true;
}
