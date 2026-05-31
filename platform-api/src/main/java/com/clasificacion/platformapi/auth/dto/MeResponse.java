package com.clasificacion.platformapi.auth.dto;

import java.util.List;

public record MeResponse(String user_id, String email, List<MembershipResponse> memberships) {
}
