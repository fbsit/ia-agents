"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useSession } from "@/shared/session/provider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { ready, session } = useSession();

  useEffect(() => {
    if (!ready) {
      return;
    }
    if (!session) {
      router.replace("/login");
    }
  }, [ready, router, session]);

  if (!ready || !session) {
    return <p>Cargando sesion...</p>;
  }

  return <>{children}</>;
}
