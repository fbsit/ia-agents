"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from "react";

import { fetchMe } from "@/shared/api/auth";
import { ApiError } from "@/shared/api/client";
import type { LoginResponse, Membership } from "@/shared/api/types";
import {
  readPersistedSession,
  SESSION_CLEARED_EVENT,
  SESSION_REFRESHED_EVENT,
  type PersistedSession,
  writePersistedSession
} from "@/shared/session/storage";

type SessionState = PersistedSession;

type SessionContextValue = {
  ready: boolean;
  session: SessionState | null;
  setFromLogin: (data: LoginResponse) => void;
  updateMemberships: (items: Membership[]) => void;
  clearSession: () => void;
  bootstrapProfile: () => Promise<boolean>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<SessionState | null>(null);
  const sessionRef = useRef<SessionState | null>(null);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    const parsed = readPersistedSession();
    if (parsed) {
      setSession(parsed);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    function syncFromStorage() {
      const parsed = readPersistedSession();
      sessionRef.current = parsed;
      setSession(parsed);
    }

    window.addEventListener(SESSION_REFRESHED_EVENT, syncFromStorage);
    window.addEventListener(SESSION_CLEARED_EVENT, syncFromStorage);
    return () => {
      window.removeEventListener(SESSION_REFRESHED_EVENT, syncFromStorage);
      window.removeEventListener(SESSION_CLEARED_EVENT, syncFromStorage);
    };
  }, []);

  const save = useCallback((next: SessionState | null) => {
    sessionRef.current = next;
    setSession(next);
    writePersistedSession(next);
  }, []);

  const setFromLogin = useCallback(
    (data: LoginResponse) => {
      save({
        userId: data.user_id,
        email: data.email,
        accessToken: data.tokens.access_token,
        refreshToken: data.tokens.refresh_token,
        memberships: data.memberships
      });
    },
    [save]
  );

  const updateMemberships = useCallback(
    (items: Membership[]) => {
      const current = sessionRef.current;
      if (!current) {
        return;
      }
      save({ ...current, memberships: items });
    },
    [save]
  );

  const clearSession = useCallback(() => {
    save(null);
  }, [save]);

  const bootstrapProfile = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) {
      return false;
    }
    try {
      const me = await fetchMe(current.accessToken);
      save({
        ...current,
        email: me.email,
        memberships: me.memberships,
        userId: me.user_id
      });
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status !== 401) {
        return true;
      }
      save(null);
      return false;
    }
  }, [save]);

  const value = useMemo<SessionContextValue>(
    () => ({ ready, session, setFromLogin, updateMemberships, clearSession, bootstrapProfile }),
    [ready, session, setFromLogin, updateMemberships, clearSession, bootstrapProfile]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession debe usarse dentro de SessionProvider");
  }
  return context;
}
