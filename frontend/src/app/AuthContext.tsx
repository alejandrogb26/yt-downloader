import { useEffect, useState } from "react";

import { getCurrentSession, logout as logoutRequest, setCsrfToken, setUnauthorizedHandler } from "../api/client";
import type { AuthUser, Profile } from "../api/types";
import { AuthContext } from "./auth-state";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);

  const clearAuth = () => {
    setUser(null);
    setProfiles([]);
    setCsrfToken(null);
  };

  useEffect(() => {
    setUnauthorizedHandler(clearAuth);
    getCurrentSession()
      .then((session) => {
        setUser(session.user);
        setProfiles(session.profiles);
        setCsrfToken(session.csrf_token);
      })
      .catch(clearAuth)
      .finally(() => setLoading(false));
    return () => setUnauthorizedHandler(null);
  }, []);

  const setAuthenticated = (
    nextUser: AuthUser,
    nextProfiles: Profile[],
    nextCsrfToken: string,
  ) => {
    setUser(nextUser);
    setProfiles(nextProfiles);
    setCsrfToken(nextCsrfToken);
  };

  const logout = async () => {
    try {
      await logoutRequest();
    } finally {
      clearAuth();
    }
  };

  return (
    <AuthContext.Provider value={{ user, profiles, loading, setAuthenticated, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
