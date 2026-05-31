package com.clasificacion.platformapi.catalog.dto;

public record FlowResponse(
    String flow_id,
    String org_id,
    String company_id,
    String name,
    String description,
    String graph_json,
    String status,
    Integer published_version
) {
}
