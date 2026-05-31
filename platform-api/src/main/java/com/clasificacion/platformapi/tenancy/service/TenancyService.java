package com.clasificacion.platformapi.tenancy.service;

import com.clasificacion.platformapi.auth.exception.InvalidCredentialsException;
import com.clasificacion.platformapi.auth.service.JwtTokenService;
import com.clasificacion.platformapi.tenancy.domain.Membership;
import com.clasificacion.platformapi.tenancy.domain.Organization;
import com.clasificacion.platformapi.tenancy.exception.TenancyException;
import com.clasificacion.platformapi.tenancy.repository.JdbcMembershipRepository;
import com.clasificacion.platformapi.tenancy.repository.JdbcOrganizationRepository;
import java.text.Normalizer;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class TenancyService {
    private final JwtTokenService tokenService;
    private final JdbcOrganizationRepository organizations;
    private final JdbcMembershipRepository memberships;

    public TenancyService(
        JwtTokenService tokenService,
        JdbcOrganizationRepository organizations,
        JdbcMembershipRepository memberships
    ) {
        this.tokenService = tokenService;
        this.organizations = organizations;
        this.memberships = memberships;
    }

    public Organization createOrganization(String authorizationHeader, String organizationName, String companyId) {
        String userId = extractUserId(authorizationHeader);
        String effectiveCompanyId = normalizeCompanyId(companyId, organizationName);
        Organization org;
        try {
            org = organizations.create(organizationName.trim(), effectiveCompanyId);
        } catch (IllegalStateException exc) {
            throw new TenancyException(exc.getMessage());
        }
        memberships.add(userId, org.orgId(), "owner");
        return org;
    }

    public List<OrganizationMembershipView> listOrganizations(String authorizationHeader) {
        String userId = extractUserId(authorizationHeader);
        List<Membership> userMemberships = memberships.listByUserId(userId);
        return userMemberships.stream()
            .map(membership -> organizations.findById(membership.orgId())
                .map(org -> new OrganizationMembershipView(org.orgId(), org.name(), org.companyId(), membership.role()))
                .orElse(null))
            .filter(item -> item != null)
            .toList();
    }

    public List<AuthMembershipView> listAuthMemberships(String userId) {
        return memberships.listByUserId(userId).stream()
            .map(membership -> new AuthMembershipView(membership.orgId(), membership.role()))
            .toList();
    }

    private String extractUserId(String authorizationHeader) {
        if (authorizationHeader == null || !authorizationHeader.startsWith("Bearer ")) {
            throw new InvalidCredentialsException("Authorization header faltante o invalido");
        }
        String token = authorizationHeader.substring("Bearer ".length()).trim();
        return tokenService.parseAccessToken(token).userId();
    }

    private String normalizeCompanyId(String companyId, String organizationName) {
        if (companyId != null && !companyId.isBlank()) {
            return companyId.trim().toLowerCase();
        }
        String normalized = Normalizer.normalize(organizationName, Normalizer.Form.NFD)
            .replaceAll("\\p{M}", "")
            .toLowerCase()
            .replaceAll("[^a-z0-9]+", "-")
            .replaceAll("^-+|-+$", "");
        if (normalized.isBlank()) {
            normalized = "org";
        }
        return normalized + "-" + UUID.randomUUID().toString().substring(0, 8);
    }

    public record OrganizationMembershipView(String orgId, String name, String companyId, String role) {
    }

    public record AuthMembershipView(String orgId, String role) {
    }
}
