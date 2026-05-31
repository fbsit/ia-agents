package com.clasificacion.platformapi.auth.dto;

import java.util.List;

public record LoginResponse(
    String user_id,
    String email,
    List<MembershipResponse> memberships,
    AuthTokensResponse tokens
) {
}
