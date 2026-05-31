"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/shared/session/provider";

export default function HomePage() {
  const router = useRouter();
  const { ready, session } = useSession();

  useEffect(() => {
    if (!ready) {
      return;
    }
    if (session) {
      router.replace("/dashboard");
      return;
    }
    router.replace("/login");
  }, [ready, router, session]);

  return (
    <section className="surface" aria-label="Inicializacion">
      <p className="mono muted">Inicializando dashboard...</p>
    </section>
  );
}
