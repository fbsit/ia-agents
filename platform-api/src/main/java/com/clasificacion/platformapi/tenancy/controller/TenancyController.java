package com.clasificacion.platformapi.tenancy.controller;

import com.clasificacion.platformapi.tenancy.dto.CreateOrgResponse;
import com.clasificacion.platformapi.tenancy.dto.OnboardingRequest;
import com.clasificacion.platformapi.tenancy.dto.OrganizationResponse;
import com.clasificacion.platformapi.tenancy.service.TenancyService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping
public class TenancyController {
    private final TenancyService tenancyService;

    public TenancyController(TenancyService tenancyService) {
        this.tenancyService = tenancyService;
    }

    @PostMapping("/orgs")
    public CreateOrgResponse createOrganization(
        @Valid @RequestBody OnboardingRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var organization = tenancyService.createOrganization(
            authorization,
            request.organization_name(),
            request.company_id()
        );
        return new CreateOrgResponse(organization.orgId(), organization.companyId(), organization.name());
    }

    @GetMapping("/orgs")
    public List<OrganizationResponse> listOrganizations(
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        return tenancyService.listOrganizations(authorization).stream()
            .map(item -> new OrganizationResponse(item.orgId(), item.name(), item.companyId(), item.role()))
            .toList();
    }
}
