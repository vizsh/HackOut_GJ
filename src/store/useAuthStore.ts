import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface AuthUser {
  id: string;
  email: string;
  role: "sme" | "consultant" | "regulator";
  organization_id: string | null;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setSession: (token: string, user: AuthUser) => void;
  logout: () => void;
}

// The real session (backend/app/auth.py) — a signed, expiring token from a
// real login, distinct from useRoleStore's cosmetic role dropdown. Business-
// layer mutations (organizations, consent, API keys) require this token;
// api.ts attaches it automatically to every request when present.
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setSession: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: "induscope-auth-store", storage: createJSONStorage(() => localStorage) }
  )
);
