package com.clasificacion.platformapi.catalog.controller;

import com.clasificacion.platformapi.catalog.dto.CreateFlowRequest;
import com.clasificacion.platformapi.catalog.dto.CreateSkillRequest;
import com.clasificacion.platformapi.catalog.dto.FlowResponse;
import com.clasificacion.platformapi.catalog.dto.PublishRequest;
import com.clasificacion.platformapi.catalog.dto.PublishResponse;
import com.clasificacion.platformapi.catalog.dto.RuntimeExecuteRequest;
import com.clasificacion.platformapi.catalog.dto.RuntimeExecuteResponse;
import com.clasificacion.platformapi.catalog.dto.SkillResponse;
import com.clasificacion.platformapi.catalog.dto.UpdateFlowRequest;
import com.clasificacion.platformapi.catalog.dto.UpdateSkillRequest;
import com.clasificacion.platformapi.catalog.service.CatalogService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping
public class CatalogController {
    private final CatalogService catalogService;

    public CatalogController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @PostMapping("/skills")
    public SkillResponse createSkill(
        @Valid @RequestBody CreateSkillRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var skill = catalogService.createSkill(authorization, request);
        return new SkillResponse(
            skill.skillId(),
            skill.orgId(),
            skill.companyId(),
            skill.name(),
            skill.description(),
            skill.definitionJson(),
            skill.status(),
            skill.publishedVersion()
        );
    }

    @GetMapping("/skills")
    public List<SkillResponse> listSkills(
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestParam("org_id") String orgId,
        @RequestParam("company_id") String companyId
    ) {
        return catalogService.listSkills(authorization, orgId, companyId).stream()
            .map(skill -> new SkillResponse(
                skill.skillId(),
                skill.orgId(),
                skill.companyId(),
                skill.name(),
                skill.description(),
                skill.definitionJson(),
                skill.status(),
                skill.publishedVersion()
            ))
            .toList();
    }

    @PatchMapping("/skills/{skillId}")
    public SkillResponse updateSkill(
        @PathVariable String skillId,
        @Valid @RequestBody UpdateSkillRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var skill = catalogService.updateSkill(authorization, skillId, request);
        return new SkillResponse(
            skill.skillId(),
            skill.orgId(),
            skill.companyId(),
            skill.name(),
            skill.description(),
            skill.definitionJson(),
            skill.status(),
            skill.publishedVersion()
        );
    }

    @PostMapping("/skills/{skillId}/publish")
    public PublishResponse publishSkill(
        @PathVariable String skillId,
        @Valid @RequestBody PublishRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        int version = catalogService.publishSkill(authorization, skillId, request.org_id(), request.company_id());
        return new PublishResponse(skillId, "skill", version, "published");
    }

    @PostMapping("/skills/{skillId}/execute")
    public RuntimeExecuteResponse executeSkill(
        @PathVariable String skillId,
        @Valid @RequestBody RuntimeExecuteRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var execution = catalogService.executePublishedSkill(authorization, skillId, request);
        return new RuntimeExecuteResponse(
            execution.execution_id(),
            execution.type(),
            execution.id(),
            execution.version(),
            execution.status(),
            execution.output()
        );
    }

    @PostMapping("/flows")
    public FlowResponse createFlow(
        @Valid @RequestBody CreateFlowRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var flow = catalogService.createFlow(authorization, request);
        return new FlowResponse(
            flow.flowId(),
            flow.orgId(),
            flow.companyId(),
            flow.name(),
            flow.description(),
            flow.graphJson(),
            flow.status(),
            flow.publishedVersion()
        );
    }

    @GetMapping("/flows")
    public List<FlowResponse> listFlows(
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestParam("org_id") String orgId,
        @RequestParam("company_id") String companyId
    ) {
        return catalogService.listFlows(authorization, orgId, companyId).stream()
            .map(flow -> new FlowResponse(
                flow.flowId(),
                flow.orgId(),
                flow.companyId(),
                flow.name(),
                flow.description(),
                flow.graphJson(),
                flow.status(),
                flow.publishedVersion()
            ))
            .toList();
    }

    @PatchMapping("/flows/{flowId}")
    public FlowResponse updateFlow(
        @PathVariable String flowId,
        @Valid @RequestBody UpdateFlowRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var flow = catalogService.updateFlow(authorization, flowId, request);
        return new FlowResponse(
            flow.flowId(),
            flow.orgId(),
            flow.companyId(),
            flow.name(),
            flow.description(),
            flow.graphJson(),
            flow.status(),
            flow.publishedVersion()
        );
    }

    @PostMapping("/flows/{flowId}/publish")
    public PublishResponse publishFlow(
        @PathVariable String flowId,
        @Valid @RequestBody PublishRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        int version = catalogService.publishFlow(authorization, flowId, request.org_id(), request.company_id());
        return new PublishResponse(flowId, "flow", version, "published");
    }

    @PostMapping("/flows/{flowId}/execute")
    public RuntimeExecuteResponse executeFlow(
        @PathVariable String flowId,
        @Valid @RequestBody RuntimeExecuteRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        var execution = catalogService.executePublishedFlow(authorization, flowId, request);
        return new RuntimeExecuteResponse(
            execution.execution_id(),
            execution.type(),
            execution.id(),
            execution.version(),
            execution.status(),
            execution.output()
        );
    }
}
