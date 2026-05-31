"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CaretDown,
  ChatCircleText,
  ChartBar,
  Gear,
  GearSix,
  House,
  Robot,
  SignOut,
  UploadSimple,
  Wrench
} from "@phosphor-icons/react";

import { OPERATIONAL_SECTIONS, findOperationalSection } from "@/features/agents/knowledge-templates";
import { logoutUser } from "@/shared/api/auth";
import { listOrganizations } from "@/shared/api/tenancy";
import type { Organization } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Resumen", icon: House },
  { href: "/agents", label: "Agentes", icon: Robot },
  { href: "/settings", label: "Configuracion", icon: Gear }
];

const AGENT_NAV_ITEMS = [
  { slug: "dashboard", label: "Dashboard", icon: ChartBar },
  { slug: "setup", label: "Setup", icon: Wrench },
  { slug: "knowledge", label: "Conocimiento", icon: UploadSimple },
  { slug: "playground", label: "Pruebas", icon: ChatCircleText },
  { slug: "deploy", label: "Despliegue", icon: GearSix }
];

function resolvePageTitle(pathname: string): string {
  if (pathname.startsWith("/agents/new")) {
    return "Nuevo agente";
  }
  if (pathname.includes("/knowledge")) {
    return "Conocimiento";
  }
  if (pathname.includes("/setup")) {
    return "Setup";
  }
  if (pathname.includes("/dashboard")) {
    return "Dashboard";
  }
  if (pathname.includes("/metrics")) {
    return "Metricas";
  }
  if (pathname.includes("/playground")) {
    return "Pruebas";
  }
  if (pathname.includes("/deploy")) {
    return "Despliegue";
  }
  if (pathname.startsWith("/agents")) {
    return "Agentes";
  }
  if (pathname.startsWith("/settings")) {
    return "Configuracion";
  }
  return "Resumen";
}

function resolveActiveHref(pathname: string, items: { href: string }[]): string | null {
  const matches = items.filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  if (matches.length === 0) {
    return null;
  }

  const sorted = [...matches].sort((left, right) => right.href.length - left.href.length);
  return sorted[0]?.href ?? null;
}

function resolveAgentId(pathname: string): string | null {
  const matches = pathname.match(/^\/agents\/([^/]+)(?:\/|$)/);
  const agentId = matches?.[1];
  if (!agentId || agentId === "new") {
    return null;
  }
  return agentId;
}

function resolveUserInitials(email: string | null | undefined): string {
  const normalized = (email ?? "").trim().toLowerCase();
  if (!normalized) {
    return "US";
  }

  const localPart = normalized.split("@")[0] ?? "";
  const tokens = localPart.split(/[._-]+/).filter(Boolean);
  if (tokens.length >= 2) {
    return `${tokens[0]?.[0] ?? ""}${tokens[1]?.[0] ?? ""}`.toUpperCase();
  }

  return localPart.slice(0, 2).toUpperCase() || "US";
}

function resolveOperationalBadge(sectionId: string): string {
  if (sectionId === "facts") {
    return "HECHOS";
  }
  if (sectionId === "rules") {
    return "REGLAS";
  }
  if (sectionId === "contracts") {
    return "CONTRATOS";
  }
  if (sectionId === "permissions") {
    return "PERMISOS";
  }
  if (sectionId === "feedback") {
    return "RETRO";
  }
  return sectionId.toUpperCase();
}

type ConsoleNavProps = {
  organizations?: Organization[];
  activeCompanyId?: string;
  onCompanyChange?: (companyId: string) => void;
};

export function ConsoleNav({ organizations, activeCompanyId, onCompanyChange }: ConsoleNavProps = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { session, clearSession } = useSession();
  const [loggingOut, setLoggingOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [tenantName, setTenantName] = useState("Sin tenant");
  const menuRef = useRef<HTMLDivElement | null>(null);
  const userInitials = resolveUserInitials(session?.email);
  const pageTitle = resolvePageTitle(pathname);
  const activeHref = resolveActiveHref(pathname, NAV_ITEMS);
  const activeAgentId = useMemo(() => resolveAgentId(pathname), [pathname]);
  const activeKnowledgeSection = useMemo(() => {
    return findOperationalSection(searchParams.get("section")).id;
  }, [searchParams]);
  const showKnowledgeSections = Boolean(activeAgentId && pathname.includes("/knowledge"));
  const knowledgeMode = Boolean(activeAgentId && pathname.includes("/knowledge"));
  const agentNavItems = useMemo(() => {
    if (!activeAgentId) {
      return [];
    }
    return AGENT_NAV_ITEMS.map((item) => ({
      href: `/agents/${activeAgentId}/${item.slug}`,
      label: item.label,
      icon: item.icon
    }));
  }, [activeAgentId]);
  const activeAgentHref = resolveActiveHref(pathname, agentNavItems);
  const providedTenantName = useMemo(() => {
    if (!organizations || organizations.length === 0) {
      return "";
    }
    const selected =
      organizations.find((item) => item.company_id === activeCompanyId) ?? organizations[0] ?? null;
    return selected?.name ?? "";
  }, [organizations, activeCompanyId]);

  useEffect(() => {
    let mounted = true;

    async function loadTenantName() {
      if (providedTenantName) {
        if (mounted) {
          setTenantName(providedTenantName);
        }
        return;
      }

      if (!session?.accessToken) {
        if (mounted) {
          setTenantName("Sin tenant");
        }
        return;
      }

      try {
        const organizations = await listOrganizations(session.accessToken);
        const preferredOrgId = session.memberships[0]?.org_id;
        const preferred =
          organizations.find((item) => item.org_id === preferredOrgId) ?? organizations[0] ?? null;
        if (!mounted) {
          return;
        }
        setTenantName(preferred?.name ?? "Sin tenant");
      } catch {
        if (!mounted) {
          return;
        }
        setTenantName("Sin tenant");
      }
    }

    void loadTenantName();
    return () => {
      mounted = false;
    };
  }, [providedTenantName, session]);

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) {
        setMenuOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  async function handleLogout() {
    if (loggingOut) {
      return;
    }

    setLoggingOut(true);
    try {
      if (session?.refreshToken) {
        await logoutUser(session.refreshToken);
      }
    } catch {
    } finally {
      setMenuOpen(false);
      clearSession();
      router.replace("/login");
      setLoggingOut(false);
    }
  }

  return (
    <>
      <aside className="console-sidebar" aria-label="Navegacion principal">
        <div className="console-sidebar-head">
          <p className="mono muted">{tenantName}</p>
          <strong>Constructor de agentes</strong>
          {organizations && organizations.length > 0 && onCompanyChange ? (
            <label className="console-tenant-picker" aria-label="Organizacion activa">
              <span className="mono muted">Organizacion activa</span>
              <select
                value={activeCompanyId ?? organizations[0]?.company_id ?? ""}
                onChange={(event) => onCompanyChange(event.target.value)}
              >
                {organizations.map((organization) => (
                  <option key={organization.org_id} value={organization.company_id}>
                    {organization.name} ({organization.company_id})
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        {activeAgentId ? (
          <Link
            href={knowledgeMode ? `/agents/${activeAgentId}/setup` : "/agents"}
            className="console-back-link"
            aria-label="Volver"
          >
            <ArrowLeft size={16} weight="bold" />
            <span>Volver</span>
          </Link>
        ) : null}

        {!activeAgentId ? (
          <nav className="console-sidebar-nav">
            {NAV_ITEMS.map((item) => {
              const active = item.href === activeHref;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={active ? "console-nav-link active" : "console-nav-link"}
                >
                  <Icon size={18} weight="duotone" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        ) : null}

        {activeAgentId ? (
          <div className="console-sidebar-group">
            {!knowledgeMode ? (
              <>
                <p className="mono muted console-sidebar-label">Agente actual</p>
                <nav className="console-sidebar-nav" aria-label="Navegacion del agente">
                  {agentNavItems.map((item) => {
                    const active = item.href === activeAgentHref;
                    const Icon = item.icon;
                    const targetHref =
                      item.href.endsWith("/knowledge") ? `${item.href}/new?section=facts` : item.href;
                    return (
                      <Link
                        key={item.href}
                        href={targetHref}
                        className={active ? "console-nav-link active" : "console-nav-link"}
                      >
                        <Icon size={18} weight="duotone" />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}
                </nav>
              </>
            ) : null}
            {showKnowledgeSections ? (
              <>
                <p className="mono muted console-sidebar-label">Bloques operativos</p>
                <nav className="console-sidebar-nav" aria-label="Bloques de conocimiento">
                  {OPERATIONAL_SECTIONS.map((section) => {
                    const href = `/agents/${activeAgentId}/knowledge/new?section=${section.id}`;
                    const active = pathname.includes("/knowledge/new") && section.id === activeKnowledgeSection;
                    return (
                      <Link
                        key={section.id}
                        href={href}
                        className={active ? "console-nav-link active" : "console-nav-link"}
                      >
                        <span className="mono">{resolveOperationalBadge(section.id)}</span>
                        <span>{section.label}</span>
                      </Link>
                    );
                  })}
                </nav>
              </>
            ) : null}
          </div>
        ) : null}
      </aside>

      <header className="console-topbar" aria-label="Topbar de sesion">
        <div className="stack compact">
          <p className="mono muted">workspace / {pageTitle.toLowerCase()}</p>
          <strong>{pageTitle}</strong>
        </div>
        <div className="console-user-menu" ref={menuRef}>
          <button
            type="button"
            className="console-user-trigger"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((previous) => !previous)}
          >
            <span className="console-user-avatar" aria-hidden="true">
              <span className="console-user-initials">{userInitials}</span>
            </span>
            <span className="console-user-copy">
              <p className="console-user-email">{session?.email ?? "Sesion activa"}</p>
            </span>
            <CaretDown
              size={14}
              weight="bold"
              className={menuOpen ? "console-user-caret caret-open" : "console-user-caret"}
            />
          </button>

          {menuOpen ? (
            <div className="console-user-dropdown" role="menu" aria-label="Menu de usuario">
              <button
                type="button"
                className="console-dropdown-action"
                onClick={() => void handleLogout()}
                disabled={loggingOut}
              >
                <SignOut size={16} weight="duotone" />
                {loggingOut ? "Saliendo..." : "Salir"}
              </button>
            </div>
          ) : null}
        </div>
      </header>
    </>
  );
}
