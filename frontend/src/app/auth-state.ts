import { createContext } from "react";

import type { AuthUser, Profile } from "../api/types";

export type AuthState = {
  user: AuthUser | null;
  profiles: Profile[];
  loading: boolean;
  setAuthenticated: (user: AuthUser, profiles: Profile[], csrfToken: string) => void;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);
