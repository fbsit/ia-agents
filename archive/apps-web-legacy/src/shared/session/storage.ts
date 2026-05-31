import type { Membership } from "@/shared/api/types";

export const SESSION_STORAGE_KEY = "clasi-web-session";
export const SESSION_REFRESHED_EVENT = "clasi-session-refreshed";
export const SESSION_CLEARED_EVENT = "clasi-session-cleared";

export type PersistedSession = {
  userId: string;
  email: string;
  accessToken: string;
  refreshToken: string;
  memberships: Membership[];
};

export function parsePersistedSession(raw: string): PersistedSession | null {
  try {
    const item = JSON.parse(raw) as PersistedSession;
    if (!item.accessToken || !item.refreshToken || !item.userId) {
      return null;
    }
    return item;
  } catch {
    return null;
  }
}

export function readPersistedSession(): PersistedSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  return parsePersistedSession(raw);
}

export function writePersistedSession(next: PersistedSession | null): void {
  if (typeof window === "undefined") {
    return;
  }

  if (!next) {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }

  window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(next));
}

export function emitSessionRefreshed(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(SESSION_REFRESHED_EVENT));
}

export function emitSessionCleared(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(SESSION_CLEARED_EVENT));
}
