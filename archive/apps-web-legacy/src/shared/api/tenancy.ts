import { apiRequest } from "@/shared/api/client";
import type { CreateOrgResponse, Organization } from "@/shared/api/types";

export function createOrganization(
  input: { organization_name: string; company_id?: string },
  accessToken: string
) {
  return apiRequest<CreateOrgResponse>(
    "/orgs",
    {
      method: "POST",
      body: JSON.stringify(input)
    },
    accessToken
  );
}

export function listOrganizations(accessToken: string) {
  return apiRequest<Organization[]>("/orgs", { method: "GET" }, accessToken);
}
