from __future__ import annotations

import logging
from typing import Any

from clasificacion_langchain.agents.commerce.checkout_link import (
    build_web_checkout_redirect as _build_web_checkout_redirect,
    build_web_checkout_redirect_from_requests as _build_web_checkout_redirect_from_requests,
    describe_web_checkout_answer as _describe_web_checkout_answer,
)
from clasificacion_langchain.agents.commerce.commands import parse_checkout_command
from clasificacion_langchain.agents.commerce.extractors import (
    canonical_tool_succeeded as _canonical_tool_succeeded,
    cart_requests_from_llm_intent as _cart_requests_from_llm_intent,
    extract_address as _extract_address,
    extract_pickup_location as _extract_pickup_location,
    is_affirmative_followup_message as _is_affirmative_followup_message,
    is_checkout_redirect_channel as _is_checkout_redirect_channel,
    is_checkout_request_message as _is_checkout_request_message,
    is_email_message as _is_email_message,
    is_login_confirmed_message as _is_login_confirmed_message,
    is_workflow_status_question as _is_workflow_status_question,
    product_lookup_queries_from_llm_intent as _product_lookup_queries_from_llm_intent,
    workflow_action as _workflow_action,
    workflow_state_bool as _workflow_state_bool,
    workflow_state_customer_authenticated as _workflow_state_customer_authenticated,
)
from clasificacion_langchain.agents.commerce.helpers import (
    is_checkout_langgraph_enabled as _is_checkout_langgraph_enabled,
    is_likely_greeting_message as _is_likely_greeting_message,
    recent_commerce_products as _recent_commerce_products,
    recent_products_for_llm as _recent_products_for_llm,
    trace_route as _trace_route,
    workflow_state_has_active_checkout as _workflow_state_has_active_checkout,
)
from clasificacion_langchain.agents.commerce.intent_parser import (
    checkout_requests_for_workflow as _checkout_requests_for_workflow,
    extract_invoice_data as _extract_invoice_data,
    generate_recipe_plan_with_openai as _generate_recipe_plan_with_openai,
    parse_commerce_intent_with_openai as _parse_commerce_intent_with_openai,
    tool_from_llm_commerce_intent as _tool_from_llm_commerce_intent,
)
from clasificacion_langchain.agents.commerce.lookup_cart import LookupCartResolver
from clasificacion_langchain.agents.commerce.prompting import build_checkout_planner_context
from clasificacion_langchain.agents.commerce.recent_products import normalize_text as _normalize_widget_text
from clasificacion_langchain.agents.commerce.resolver import CheckoutWorkflowResolver
from clasificacion_langchain.agents.commerce.resume_timeout import (
    describe_current_workflow as _describe_current_workflow,
)
from clasificacion_langchain.agents.commerce.router import CommerceWorkflowRouter
from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState, coerce_workflow_state
from clasificacion_langchain.agents.commerce.checkout_resolver import (
    resolve_checkout_items as _resolve_checkout_items,
    resolve_checkout_order_confirmation_followup as _resolve_checkout_order_confirmation_followup,
    resolve_checkout_payment_followup as _resolve_checkout_payment_followup,
)
from clasificacion_langchain.agents.commerce.tool_executor import CanonicalCommerceToolExecutor
from clasificacion_langchain.agents.commerce.widget_payload import (
    build_multi_cart_tool_payload as _build_multi_cart_tool_payload,
    build_multi_product_lookup_payload as _build_multi_product_lookup_payload,
    build_recipe_recommendation_payload as _build_recipe_recommendation_payload,
    format_public_widget_tool_payload as _format_public_widget_tool_payload,
)
from clasificacion_langchain.agents.commerce_workflow import (
    build_state as build_workflow_state,
    resolve_transition as resolve_workflow_transition,
)
from clasificacion_langchain.integrations.clubhx import ClubHxToolsClient


logger = logging.getLogger(__name__)


def tool_for_intent(intent_label: str, message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        recent_products=_recent_products_for_llm(session_id),
        intent_label=intent_label,
        channel="api",
    )
    llm_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
    if llm_tool:
        return llm_tool
    return None


def forced_commerce_tool(message: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    if not (message or "").strip():
        return None
    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        recent_products=_recent_products_for_llm(session_id),
        intent_label=None,
        channel="api",
    )
    llm_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
    if llm_tool:
        return llm_tool
    return None


def plan_checkout_command(state: WhatsAppCheckoutState) -> Any:
    parsed = _parse_commerce_intent_with_openai(
        state.user_goal,
        session_id=state.session_id,
        recent_products=_recent_products_for_llm(state.session_id),
        intent_label=None,
        channel=state.channel,
        response_style_context="",
        workflow_context=build_checkout_planner_context(
            workflow_stage=state.stage,
            checkout_stage=state.checkout_stage,
            pending_next_step=state.pending_next_step,
            otp_email=state.otp_email,
        ),
    )
    return parse_checkout_command(parsed)


def run_commerce_workflow_router(
    *,
    company_id: str,
    agent_id: str | None,
    user_id: str,
    session_id: str,
    message: str,
    channel: str,
    clubhx_tools_client: ClubHxToolsClient | None,
    intent_label: str | None,
    response_style_context: str | None,
    workflow_state: dict[str, str] | None,
    agent_service: Any | None = None,
    resolve_affirmative_followup: Any | None = None,
    resolve_greeting_followup: Any | None = None,
    resolve_workflow_resume: Any | None = None,
    legacy_preflight: Any | None = None,
    resolve_checkout_followup: Any | None = None,
    update_memory: Any | None = None,
    fetch_addresses: Any | None = None,
    create_address: Any | None = None,
    process_reminders: Any | None = None,
) -> dict[str, Any] | None:
    def _legacy_resolver(
        state: WhatsAppCheckoutState,
        _command: Any,
    ) -> dict[str, Any] | None:
        return resolve_shared_commerce_payload_legacy(
            company_id=state.company_id,
            agent_id=state.agent_id or None,
            user_id=state.user_id,
            session_id=state.session_id,
            message=state.user_goal,
            channel=state.channel,
            clubhx_tools_client=clubhx_tools_client,
            intent_label=intent_label,
            response_style_context=response_style_context,
            workflow_state=state.to_workflow_state_dict(),
            agent_service=agent_service,
            resolve_affirmative_followup=resolve_affirmative_followup,
            resolve_greeting_followup=resolve_greeting_followup,
            resolve_workflow_resume=resolve_workflow_resume,
            legacy_preflight=legacy_preflight,
            resolve_checkout_followup=resolve_checkout_followup,
            update_memory=update_memory,
            fetch_addresses=fetch_addresses,
            create_address=create_address,
            process_reminders=process_reminders,
        )

    def _clear_timeout_markers() -> None:
        if agent_service is None or not agent_id:
            return
        agent_service.update_session_summary(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            workflow_reset_started_at="",
            workflow_timeout_sent_at="",
        )

    resolver = CheckoutWorkflowResolver(
        executor=CanonicalCommerceToolExecutor(clubhx_tools_client),
        fallback=_legacy_resolver,
        recent_products_provider=_recent_commerce_products,
        clear_timeout_markers=_clear_timeout_markers,
        is_affirmative_message=_is_affirmative_followup_message,
        is_greeting_message=_is_likely_greeting_message,
    )

    router = CommerceWorkflowRouter(
        planner=plan_checkout_command,
        resolver=resolver.resolve,
        commerce_client=clubhx_tools_client,
    )
    return router.process_turn(
        company_id=company_id,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
        message=message,
        channel=channel,
        workflow_state=workflow_state,
    )


def resolve_lookup_cart_via_workflow_modules(
    *,
    company_id: str,
    agent_id: str | None,
    user_id: str,
    session_id: str,
    message: str,
    channel: str,
    clubhx_tools_client: ClubHxToolsClient | None,
    workflow_state: dict[str, str] | None,
    llm_commerce_intent: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if clubhx_tools_client is None:
        return None
    resolver = LookupCartResolver(
        executor=CanonicalCommerceToolExecutor(clubhx_tools_client),
        recent_products_provider=_recent_commerce_products,
    )
    state = coerce_workflow_state(
        company_id=company_id,
        agent_id=agent_id or "",
        session_id=session_id,
        channel=channel,
        workflow_state=workflow_state,
        user_id=user_id,
    )
    state.user_goal = message.strip()
    resolution = resolver.resolve(state, parse_checkout_command(llm_commerce_intent))
    return resolution.payload if resolution.handled else None


def resolve_shared_commerce_payload(
    *,
    company_id: str,
    agent_id: str | None = None,
    user_id: str,
    session_id: str,
    message: str,
    channel: str,
    clubhx_tools_client: ClubHxToolsClient | None,
    intent_label: str | None = None,
    response_style_context: str | None = None,
    workflow_state: dict[str, str] | None = None,
    agent_service: Any | None = None,
    resolve_affirmative_followup: Any | None = None,
    resolve_greeting_followup: Any | None = None,
    resolve_workflow_resume: Any | None = None,
    legacy_preflight: Any | None = None,
    resolve_checkout_followup: Any | None = None,
    update_memory: Any | None = None,
    fetch_addresses: Any | None = None,
    create_address: Any | None = None,
    process_reminders: Any | None = None,
) -> dict[str, Any] | None:
    has_active_workflow = _workflow_state_has_active_checkout(workflow_state)
    if (
        clubhx_tools_client is None
        or not _is_checkout_langgraph_enabled()
        or (_is_likely_greeting_message(message) and has_active_workflow)
    ):
        return resolve_shared_commerce_payload_legacy(
            company_id=company_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            message=message,
            channel=channel,
            clubhx_tools_client=clubhx_tools_client,
            intent_label=intent_label,
            response_style_context=response_style_context,
            workflow_state=workflow_state,
            agent_service=agent_service,
            resolve_affirmative_followup=resolve_affirmative_followup,
            resolve_greeting_followup=resolve_greeting_followup,
            resolve_workflow_resume=resolve_workflow_resume,
            legacy_preflight=legacy_preflight,
            resolve_checkout_followup=resolve_checkout_followup,
            update_memory=update_memory,
            fetch_addresses=fetch_addresses,
            create_address=create_address,
            process_reminders=process_reminders,
        )
    return run_commerce_workflow_router(
        company_id=company_id,
        agent_id=agent_id,
        user_id=user_id,
        session_id=session_id,
        message=message,
        channel=channel,
        clubhx_tools_client=clubhx_tools_client,
        intent_label=intent_label,
        response_style_context=response_style_context,
        workflow_state=workflow_state,
        agent_service=agent_service,
        resolve_affirmative_followup=resolve_affirmative_followup,
        resolve_greeting_followup=resolve_greeting_followup,
        resolve_workflow_resume=resolve_workflow_resume,
        legacy_preflight=legacy_preflight,
        resolve_checkout_followup=resolve_checkout_followup,
        update_memory=update_memory,
        fetch_addresses=fetch_addresses,
        create_address=create_address,
        process_reminders=process_reminders,
    )


def resolve_shared_commerce_payload_legacy(
    *,
    company_id: str,
    agent_id: str | None = None,
    user_id: str,
    session_id: str,
    message: str,
    channel: str,
    clubhx_tools_client: ClubHxToolsClient | None,
    intent_label: str | None = None,
    response_style_context: str | None = None,
    workflow_state: dict[str, str] | None = None,
    agent_service: Any | None = None,
    resolve_affirmative_followup: Any | None = None,
    resolve_greeting_followup: Any | None = None,
    resolve_workflow_resume: Any | None = None,
    legacy_preflight: Any | None = None,
    resolve_checkout_followup: Any | None = None,
    update_memory: Any | None = None,
    fetch_addresses: Any | None = None,
    create_address: Any | None = None,
    process_reminders: Any | None = None,
) -> dict[str, Any] | None:
    if clubhx_tools_client is None:
        _trace_route(
            "commerce.skip_no_tools_client",
            session_id=session_id,
            channel=channel,
            message=message,
        )
        logger.warning(
            "commerce_router_skip reason=no_tools_client session_id=%s channel=%s message=%s",
            session_id,
            channel,
            message,
        )
        return None

    normalized_message = message
    _trace_route(
        "commerce.start",
        session_id=session_id,
        channel=channel,
        message=normalized_message,
        greeting_like=_is_likely_greeting_message(message),
        workflow_stage=str((workflow_state or {}).get("stage") or ""),
        checkout_stage=str((workflow_state or {}).get("checkout_stage") or ""),
        pending_next_step=str((workflow_state or {}).get("pending_next_step") or ""),
    )
    logger.warning(
        "commerce_router_start session_id=%s channel=%s greeting_like=%s message=%s workflow_stage=%s checkout_stage=%s pending_next_step=%s",
        session_id,
        channel,
        _is_likely_greeting_message(message),
        normalized_message,
        str((workflow_state or {}).get("stage") or ""),
        str((workflow_state or {}).get("checkout_stage") or ""),
        str((workflow_state or {}).get("pending_next_step") or ""),
    )

    greeting_like = _is_likely_greeting_message(message)
    if legacy_preflight is not None:
        preflight_payload = legacy_preflight(
            company_id=company_id,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            channel=channel,
            workflow_state=workflow_state,
        )
        if preflight_payload is not None:
            return preflight_payload
    has_active_workflow = _workflow_state_has_active_checkout(workflow_state)
    if resolve_greeting_followup is not None:
        greeting_followup_payload = resolve_greeting_followup(
            message=message,
            workflow_state=workflow_state,
        )
        if greeting_followup_payload:
            _trace_route(
                "commerce.resolve_greeting_followup",
                session_id=session_id,
                intent=str(greeting_followup_payload.get("intent_label") or ""),
                workflow_stage=str(greeting_followup_payload.get("workflow_stage") or ""),
                checkout_stage=str(greeting_followup_payload.get("checkout_stage") or ""),
            )
            logger.info(
                "commerce_router_greeting_followup session_id=%s intent=%s workflow_stage=%s checkout_stage=%s",
                session_id,
                str(greeting_followup_payload.get("intent_label") or ""),
                str(greeting_followup_payload.get("workflow_stage") or ""),
                str(greeting_followup_payload.get("checkout_stage") or ""),
            )
            return greeting_followup_payload
    if _is_workflow_status_question(message) and has_active_workflow:
        intent_label_resolved, workflow_stage, checkout_stage, description = _describe_current_workflow(workflow_state)
        pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip()
        payload = {
            "answer": f"{description} Si quieres, te voy guiando con el siguiente paso.",
            "intent_label": intent_label_resolved,
            "workflow_stage": workflow_stage,
            "checkout_stage": checkout_stage,
            "pending_next_step": pending_next_step,
        }
        _trace_route(
            "commerce.resolve_workflow_status",
            session_id=session_id,
            intent=intent_label_resolved,
            workflow_stage=workflow_stage,
            checkout_stage=checkout_stage,
        )
        logger.info(
            "commerce_router_workflow_status session_id=%s intent=%s workflow_stage=%s checkout_stage=%s",
            session_id,
            intent_label_resolved,
            workflow_stage,
            checkout_stage,
        )
        return payload
    if greeting_like and not has_active_workflow:
        _trace_route(
            "commerce.greeting_passthrough",
            session_id=session_id,
            channel=channel,
            message=message,
        )
        logger.info(
            "commerce_router_greeting_passthrough session_id=%s channel=%s message=%s",
            session_id,
            channel,
            message,
        )
        return None

    llm_commerce_intent = _parse_commerce_intent_with_openai(
        message,
        session_id=session_id,
        recent_products=_recent_products_for_llm(session_id),
        intent_label=intent_label,
        channel=channel,
        response_style_context=response_style_context,
        workflow_context=(
            f"stage={str((workflow_state or {}).get('stage') or '')};"
            f"checkout_stage={str((workflow_state or {}).get('checkout_stage') or '')};"
            f"pending_next_step={str((workflow_state or {}).get('pending_next_step') or '')};"
            f"otp_email={str((workflow_state or {}).get('otp_email') or '')}"
        ),
    )

    current_invoice_data = _extract_invoice_data(message, session_id=session_id)
    current_workflow = build_workflow_state(
        stage=(workflow_state or {}).get("stage"),
        checkout_stage=(workflow_state or {}).get("checkout_stage"),
        selected_products=(workflow_state or {}).get("selected_products"),
        shipping_preference=(workflow_state or {}).get("shipping_preference") or (message if any(token in _normalize_widget_text(message) for token in ["envio", "despacho", "retiro", "comuna"]) else ""),
        pickup_location_label=(workflow_state or {}).get("pickup_location_label") or _extract_pickup_location(message),
        delivery_address=(workflow_state or {}).get("delivery_address") or _extract_address(message),
        delivery_address_confirmed=_workflow_state_bool((workflow_state or {}).get("delivery_address_confirmed")),
        invoice_type=(workflow_state or {}).get("invoice_type") or current_invoice_data.get("invoice_type"),
        invoice_rut=(workflow_state or {}).get("invoice_rut") or current_invoice_data.get("rut"),
        invoice_business_name=(workflow_state or {}).get("invoice_business_name") or current_invoice_data.get("business_name"),
        invoice_address=(workflow_state or {}).get("invoice_address") or current_invoice_data.get("invoice_address"),
        payment_preference=(workflow_state or {}).get("payment_preference") or (message if any(token in _normalize_widget_text(message) for token in ["pago", "tarjeta", "transferencia", "link de pago"]) else ""),
        customer_authenticated=_workflow_state_customer_authenticated(workflow_state) or _is_login_confirmed_message(message),
        order_reference=(workflow_state or {}).get("order_reference") or "",
    )
    logger.info(
        "commerce_workflow_snapshot session_id=%s stage=%s checkout_stage=%s pending_next_step=%s authenticated=%s otp_email=%s selected_products=%s shipping_preference=%s",
        session_id,
        str((workflow_state or {}).get("stage") or ""),
        str((workflow_state or {}).get("checkout_stage") or ""),
        str((workflow_state or {}).get("pending_next_step") or ""),
        _workflow_state_customer_authenticated(workflow_state),
        str((workflow_state or {}).get("otp_email") or ""),
        str((workflow_state or {}).get("selected_products") or ""),
        str((workflow_state or {}).get("shipping_preference") or ""),
    )

    from clasificacion_langchain.agents.commerce.helpers import resolve_quantity_or_action_followup

    quantity_or_action_payload = resolve_quantity_or_action_followup(
        company_id=company_id,
        user_id=user_id,
        channel=channel,
        message=message,
        session_id=session_id,
        workflow_state=workflow_state,
        clubhx_tools_client=clubhx_tools_client,
    )
    if quantity_or_action_payload:
        _trace_route(
            "commerce.resolve_quantity_or_action_followup",
            session_id=session_id,
            workflow_stage=str(quantity_or_action_payload.get("workflow_stage") or ""),
            pending_next_step=str(quantity_or_action_payload.get("pending_next_step") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=quantity_or_action_followup session_id=%s product=%s quantity=%s",
            session_id,
            str((((quantity_or_action_payload.get("cart_action") or {}).get("item") or {}).get("name") or "")),
            str((((quantity_or_action_payload.get("cart_action") or {}).get("item") or {}).get("quantity") or "")),
        )
        return quantity_or_action_payload

    if resolve_affirmative_followup is not None:
        followup_payload = resolve_affirmative_followup(
            message=message,
            workflow_state=workflow_state,
        )
        if followup_payload:
            _trace_route(
                "commerce.resolve_affirmative_followup",
                session_id=session_id,
                intent=str(followup_payload.get("intent_label") or ""),
                workflow_stage=str(followup_payload.get("workflow_stage") or ""),
            )
            logger.warning(
                "commerce_router_resolved kind=affirmative_followup session_id=%s payload_intent=%s workflow_stage=%s pending_next_step=%s",
                session_id,
                str(followup_payload.get("intent_label") or ""),
                str(followup_payload.get("workflow_stage") or ""),
                str(followup_payload.get("pending_next_step") or ""),
            )
            return followup_payload

    if resolve_checkout_followup is not None:
        checkout_followup_payload = resolve_checkout_followup(
            message=message,
            session_id=session_id,
            workflow_state=workflow_state,
            company_id=company_id,
            channel=channel,
            user_id=user_id,
            clubhx_tools_client=clubhx_tools_client,
        )
        if checkout_followup_payload:
            _trace_route(
                "commerce.resolve_checkout_followup",
                session_id=session_id,
                intent=str(checkout_followup_payload.get("intent_label") or ""),
                workflow_stage=str(checkout_followup_payload.get("workflow_stage") or ""),
                checkout_stage=str(checkout_followup_payload.get("checkout_stage") or ""),
            )
            logger.warning(
                "commerce_router_resolved kind=checkout_followup session_id=%s payload_intent=%s workflow_stage=%s checkout_stage=%s",
                session_id,
                str(checkout_followup_payload.get("intent_label") or ""),
                str(checkout_followup_payload.get("workflow_stage") or ""),
                str(checkout_followup_payload.get("checkout_stage") or ""),
            )
            return checkout_followup_payload

    checkout_payment_payload = _resolve_checkout_payment_followup(
        message=message,
        session_id=session_id,
        workflow_state=workflow_state,
        company_id=company_id,
        channel=channel,
        user_id=user_id,
        clubhx_tools_client=clubhx_tools_client,
    )
    if checkout_payment_payload:
        _trace_route(
            "commerce.resolve_checkout_payment_followup",
            session_id=session_id,
            intent=str(checkout_payment_payload.get("intent_label") or ""),
            workflow_stage=str(checkout_payment_payload.get("workflow_stage") or ""),
            checkout_stage=str(checkout_payment_payload.get("checkout_stage") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=checkout_payment_followup session_id=%s payload_intent=%s workflow_stage=%s checkout_stage=%s",
            session_id,
            str(checkout_payment_payload.get("intent_label") or ""),
            str(checkout_payment_payload.get("workflow_stage") or ""),
            str(checkout_payment_payload.get("checkout_stage") or ""),
        )
        return checkout_payment_payload

    checkout_order_confirmation_payload = _resolve_checkout_order_confirmation_followup(
        message=message,
        session_id=session_id,
        workflow_state=workflow_state,
        company_id=company_id,
        channel=channel,
        user_id=user_id,
        clubhx_tools_client=clubhx_tools_client,
        recent_products=_recent_commerce_products(session_id or ""),
    )
    if checkout_order_confirmation_payload:
        _trace_route(
            "commerce.resolve_checkout_order_confirmation",
            session_id=session_id,
            intent=str(checkout_order_confirmation_payload.get("intent_label") or ""),
            workflow_stage=str(checkout_order_confirmation_payload.get("workflow_stage") or ""),
            checkout_stage=str(checkout_order_confirmation_payload.get("checkout_stage") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=checkout_order_confirmation session_id=%s payload_intent=%s workflow_stage=%s checkout_stage=%s",
            session_id,
            str(checkout_order_confirmation_payload.get("intent_label") or ""),
            str(checkout_order_confirmation_payload.get("workflow_stage") or ""),
            str(checkout_order_confirmation_payload.get("checkout_stage") or ""),
        )
        return checkout_order_confirmation_payload
    logger.info(
        "commerce_checkout_followup_miss session_id=%s checkout_stage=%s pending_next_step=%s message=%s llm_intent=%s",
        session_id,
        str((workflow_state or {}).get("checkout_stage") or ""),
        str((workflow_state or {}).get("pending_next_step") or ""),
        message,
        str((llm_commerce_intent or {}).get("intent") or ""),
    )

    lookup_cart_payload = resolve_lookup_cart_via_workflow_modules(
        company_id=company_id,
        agent_id=agent_id,
        user_id=user_id,
        channel=channel,
        message=message,
        session_id=session_id,
        workflow_state=workflow_state,
        clubhx_tools_client=clubhx_tools_client,
        llm_commerce_intent=llm_commerce_intent if isinstance(llm_commerce_intent, dict) else None,
    )
    if lookup_cart_payload:
        _trace_route(
            "commerce.resolve_lookup_cart_workflow_modules",
            session_id=session_id,
            workflow_stage=str(lookup_cart_payload.get("workflow_stage") or ""),
            pending_next_step=str(lookup_cart_payload.get("pending_next_step") or ""),
            intent=str(lookup_cart_payload.get("intent_label") or ""),
        )
        logger.warning(
            "commerce_router_resolved kind=lookup_cart_workflow_modules session_id=%s intent=%s summary=%s",
            session_id,
            str(lookup_cart_payload.get("intent_label") or ""),
            str(lookup_cart_payload.get("answer") or "")[:180],
        )
        return lookup_cart_payload

    if isinstance(llm_commerce_intent, dict):
        _trace_route(
            "commerce.llm_intent",
            session_id=session_id,
            intent=str(llm_commerce_intent.get("intent") or ""),
            tool=str(llm_commerce_intent.get("tool") or ""),
            query=str(llm_commerce_intent.get("query") or ""),
            needs_clarification=bool(llm_commerce_intent.get("needs_clarification")),
        )
        logger.warning(
            "commerce_router_llm_intent session_id=%s intent=%s tool=%s needs_clarification=%s query=%s",
            session_id,
            str(llm_commerce_intent.get("intent") or ""),
            str(llm_commerce_intent.get("tool") or ""),
            bool(llm_commerce_intent.get("needs_clarification")),
            str(llm_commerce_intent.get("query") or ""),
        )

        llm_intent_name = str(llm_commerce_intent.get("intent") or "").strip().lower()
        llm_tool_name = str(llm_commerce_intent.get("tool") or "").strip().lower()

        payment_preference_text = _normalize_widget_text(str((workflow_state or {}).get("payment_preference") or ""))
        message_payment_text = _normalize_widget_text(message)
        is_whatsapp_like_channel = (channel or "").strip().lower() in {"api", "api_internal", "whatsapp", "widget_whatsapp"}
        payment_tool_override: tuple[str, dict[str, Any]] | None = None
        current_checkout_stage_name = str((workflow_state or {}).get("checkout_stage") or "").strip().lower()
        current_pending_next_step_name = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
        if (
            not _is_checkout_redirect_channel(channel)
            and is_whatsapp_like_channel
            and llm_intent_name in {"payment_options", "create_payment_link", "create_order_draft"}
        ):
            if any(token in message_payment_text or token in payment_preference_text for token in ["mercado pago", "mercadopago", "mp", "link de pago", "pago con tarjeta", "tarjeta"]):
                payment_tool_override = ("create_order_draft", {"session_id": session_id, "payment_preference": "mercado_pago"})
            elif any(token in message_payment_text or token in payment_preference_text for token in ["transferencia", "transfer", "trasferencia"]):
                payment_tool_override = ("create_order_draft", {"session_id": session_id, "payment_preference": "transferencia"})

        if current_checkout_stage_name == "order_summary_pending" or current_pending_next_step_name == "order_confirmation":
            payment_tool_override = None

        if _is_checkout_redirect_channel(channel) and (
            llm_intent_name in {"create_payment_link", "payment_options"}
            or llm_tool_name in {"create_payment_link", "get_payment_options"}
            or _is_checkout_request_message(message)
        ):
            checkout_link = _build_web_checkout_redirect(
                client=clubhx_tools_client,
                workflow_state=workflow_state,
                session_id=session_id,
            )
            _trace_route(
                "commerce.resolve_web_checkout_redirect",
                session_id=session_id,
                intent=llm_intent_name,
                tool=llm_tool_name,
                checkout_url=bool(checkout_link),
            )
            if checkout_link is None:
                return {
                    "answer": "No pude armar el link de compra ahora mismo. Decime que producto queres y seguimos por aca.",
                    "intent_label": llm_intent_name or "checkout_web",
                }
            return {
                "answer": _describe_web_checkout_answer(checkout_link),
                "intent_label": llm_intent_name or "checkout_web",
                "workflow_stage": "checkout_ready",
                "checkout_stage": "web_checkout_redirect",
                "pending_next_step": "payment_selection",
                "redirect_to": checkout_link.url,
                "workflow_action": _workflow_action(
                    "open_checkout",
                    redirect_to=checkout_link.url,
                ),
            }

        if bool(llm_commerce_intent.get("needs_clarification")):
            clarification = str(llm_commerce_intent.get("clarification_question") or "").strip()
            if clarification:
                _trace_route(
                    "commerce.resolve_clarification",
                    session_id=session_id,
                    intent=str(llm_commerce_intent.get("intent") or ""),
                    clarification=clarification,
                )
                logger.warning(
                    "commerce_router_resolved kind=clarification session_id=%s intent=%s question=%s",
                    session_id,
                    str(llm_commerce_intent.get("intent") or ""),
                    clarification,
                )
                return {"answer": clarification}

        planned_tool = _tool_from_llm_commerce_intent(llm_commerce_intent, session_id)
        if payment_tool_override and planned_tool and planned_tool[0] in {"get_payment_options", "create_payment_link", "create_order_draft"}:
            planned_tool = payment_tool_override
        elif payment_tool_override and planned_tool is None:
            planned_tool = payment_tool_override
        if planned_tool is None and llm_intent_name in {"create_payment_link", "create_order_draft", "checkout"} and current_pending_next_step_name != "order_confirmation":
            planned_tool = (llm_intent_name, {"session_id": session_id})
        transition = resolve_workflow_transition(
            current=current_workflow,
            intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
            tool_name=planned_tool[0] if planned_tool else None,
        )
        if not transition.allowed and transition.clarification:
            _trace_route(
                "commerce.blocked",
                session_id=session_id,
                intent=str(llm_commerce_intent.get("intent") or ""),
                tool=planned_tool[0] if planned_tool else "",
                clarification=transition.clarification,
            )
            logger.warning(
                "commerce_router_blocked session_id=%s intent=%s tool=%s clarification=%s",
                session_id,
                str(llm_commerce_intent.get("intent") or ""),
                planned_tool[0] if planned_tool else "",
                transition.clarification,
            )
            return {
                "answer": transition.clarification,
                "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "commerce").strip() or "commerce",
            }
        if planned_tool and planned_tool[0] in {"get_order_status", "get_shipping_options", "get_payment_options", "get_product_availability"}:
            _trace_route(
                "commerce.tool_call",
                session_id=session_id,
                tool=planned_tool[0],
                arguments=planned_tool[1],
            )
            logger.warning(
                "commerce_router_tool_call session_id=%s tool=%s arguments=%s",
                session_id,
                planned_tool[0],
                planned_tool[1],
            )
            canonical = clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool=planned_tool[0],
                channel=channel,
                user_id=user_id,
                arguments=planned_tool[1],
            )
            payload = _format_public_widget_tool_payload(
                canonical,
                user_message=message,
                intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
                channel=channel,
                session_id=session_id,
            )
            if payload:
                _trace_route(
                    "commerce.resolve_tool_payload",
                    session_id=session_id,
                    tool=planned_tool[0],
                    intent=str(payload.get("intent_label") or llm_commerce_intent.get("intent") or ""),
                    workflow_stage=str(payload.get("workflow_stage") or transition.next_stage),
                )
                logger.warning(
                    "commerce_router_resolved kind=tool_payload session_id=%s tool=%s payload_intent=%s workflow_stage=%s",
                    session_id,
                    planned_tool[0],
                    str(payload.get("intent_label") or llm_commerce_intent.get("intent") or ""),
                    str(payload.get("workflow_stage") or transition.next_stage),
                )
                payload.setdefault("intent_label", str(llm_commerce_intent.get("intent") or "commerce").strip() or "commerce")
                payload.setdefault("workflow_stage", transition.next_stage)
                return payload

        payment_checkout_tool = payment_tool_override or planned_tool
        if payment_checkout_tool and payment_checkout_tool[0] in {"create_order_draft", "create_payment_link"} and current_pending_next_step_name != "order_confirmation":
            planned_tool = payment_checkout_tool
            _trace_route(
                "commerce.checkout_tool",
                session_id=session_id,
                tool=planned_tool[0],
                checkout_stage=str(getattr(current_workflow, "checkout_stage", "") or ""),
                pending_next_step=str((workflow_state or {}).get("pending_next_step") or ""),
                payment_preference=str((workflow_state or {}).get("payment_preference") or ""),
                invoice_type=str((workflow_state or {}).get("invoice_type") or ""),
            )
            logger.warning(
                "commerce_router_checkout_tool session_id=%s tool=%s",
                session_id,
                planned_tool[0],
            )
            cart_requests = _checkout_requests_for_workflow(message, session_id, llm_commerce_intent, workflow_state, recent_products=_recent_commerce_products(session_id))
            if not cart_requests:
                if _is_checkout_redirect_channel(channel):
                    return {
                        "answer": "Todavia no tenes nada en el carrito. Decime que producto queres y te armo el link de compra.",
                        "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "checkout_web").strip() or "checkout_web",
                    }
                recent = _recent_commerce_products(session_id)
                if recent:
                    cart_requests = [
                        {"product_query": p.get("name", ""), "quantity": 1}
                        for p in recent[:3] if p.get("name")
                    ]
                    logger.warning(
                        "commerce_checkout_recent_fallback session_id=%s cart_requests=%s",
                        session_id, cart_requests,
                    )
                if not cart_requests:
                    return {
                        "answer": "Primero decime que producto queres llevar y te ayudo con el pago.",
                        "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "commerce").strip() or "commerce",
                    }
            if _is_checkout_redirect_channel(channel):
                # Web no completa OTP/pago por chat: arma el link real del
                # carrito preseleccionado y que el cliente inicie sesion y
                # pague en el storefront, igual que la rama generica de arriba.
                checkout_link = _build_web_checkout_redirect_from_requests(
                    client=clubhx_tools_client,
                    cart_requests=cart_requests,
                    session_id=session_id,
                )
                _trace_route(
                    "commerce.resolve_web_checkout_redirect_from_requests",
                    session_id=session_id,
                    tool=planned_tool[0],
                    checkout_url=bool(checkout_link),
                )
                if checkout_link is None:
                    return {
                        "answer": "No pude armar el link de compra ahora mismo. Decime que producto queres y seguimos por aca.",
                        "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "checkout_web").strip() or "checkout_web",
                    }
                return {
                    "answer": _describe_web_checkout_answer(checkout_link),
                    "intent_label": str(llm_commerce_intent.get("intent") or intent_label or "checkout_web").strip() or "checkout_web",
                    "workflow_stage": "checkout_ready",
                    "checkout_stage": "web_checkout_redirect",
                    "pending_next_step": "payment_selection",
                    "redirect_to": checkout_link.url,
                    "workflow_action": _workflow_action(
                        "open_checkout",
                        redirect_to=checkout_link.url,
                    ),
                }
            final_summary_stage = str(getattr(current_workflow, "checkout_stage", "") or "").strip() in {
                "order_summary_confirmed",
            }
            if not current_workflow.customer_authenticated and not final_summary_stage:
                if _is_email_message(message):
                    send_ok = False
                    if clubhx_tools_client is not None:
                        try:
                            result = clubhx_tools_client.execute_canonical(
                                tenant_id=company_id,
                                tool="send_verification_code",
                                channel=channel,
                                user_id=user_id,
                                arguments={"email": message.strip()},
                            )
                            logger.info(
                                "send_verification_code_ok session_id=%s email=%s result=%s",
                                session_id, message.strip(), result,
                            )
                            send_ok = _canonical_tool_succeeded(result, expected_statuses={"sent", "ok", "success"})
                        except Exception as exc:
                            logger.warning("send_verification_code_failed session_id=%s email=%s detail=%s", session_id, message.strip(), exc)
                    if not send_ok:
                        return {
                            "answer": "No pude enviar el código de verificación. Probá de nuevo con tu correo.",
                            "intent_label": "checkout_otp_send_failed",
                            "workflow_stage": "checkout_ready",
                            "checkout_stage": "auth_pending",
                            "pending_next_step": "auth_confirmation",
                            "workflow_action": _workflow_action("otp_send_failed"),
                        }
                    return {
                        "answer": f"Te enviamos un codigo de verificacion a {message.strip()}. Ingresalo aca para continuar.",
                        "intent_label": "checkout_otp_sent",
                        "workflow_stage": "checkout_ready",
                        "checkout_stage": "otp_pending",
                        "pending_next_step": "otp_verification",
                        "otp_email": message.strip(),
                        "workflow_action": _workflow_action("otp_sent"),
                    }
                return {
                    "answer": "Para seguir con el pago necesito que inicies sesion primero. Escribe tu correo electronico para enviarte un codigo de verificacion.",
                    "intent_label": "checkout_auth_needed",
                    "workflow_stage": "checkout_ready",
                    "checkout_stage": "auth_pending",
                    "pending_next_step": "auth_confirmation",
                    "workflow_action": _workflow_action("request_auth"),
                }
            checkout_items, checkout_products = _resolve_checkout_items(
                company_id=company_id,
                user_id=user_id,
                channel=channel,
                session_id=session_id,
                cart_requests=cart_requests,
                clubhx_tools_client=clubhx_tools_client,
            )
            if not checkout_items:
                return {"answer": "No pude validar los productos del pedido. Si quieres, dime el nombre exacto del producto y la cantidad."}
            canonical = clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool=planned_tool[0],
                channel=channel,
                user_id=user_id,
                arguments={
                    **planned_tool[1],
                    "items": checkout_items,
                    "session_id": session_id,
                },
            )
            payload = _format_public_widget_tool_payload(
                canonical,
                user_message=message,
                intent_label=str(llm_commerce_intent.get("intent") or intent_label or ""),
                channel=channel,
                session_id=session_id,
            )
            if payload:
                _trace_route(
                    "commerce.resolve_checkout_payload",
                    session_id=session_id,
                    tool=planned_tool[0],
                    checkout_stage=str(payload.get("checkout_stage") or ""),
                    reset=bool(payload.get("reset_workflow")),
                )
                logger.warning(
                    "commerce_router_resolved kind=checkout_payload session_id=%s tool=%s checkout_stage=%s reset=%s",
                    session_id,
                    planned_tool[0],
                    str(payload.get("checkout_stage") or ""),
                    bool(payload.get("reset_workflow")),
                )
                if checkout_products and not payload.get("products"):
                    payload["products"] = checkout_products[:6]
                payload.setdefault("intent_label", str(llm_commerce_intent.get("intent") or "commerce").strip() or "commerce")
                payload.setdefault("workflow_stage", transition.next_stage)
                return payload

    if str((llm_commerce_intent or {}).get("intent") or "").strip().lower() == "recipe_recommendation":
        recipe_plan = _generate_recipe_plan_with_openai(message, session_id, _recent_commerce_products(session_id))
        if isinstance(recipe_plan, dict):
            ingredient_queries: list[str] = []
            seen_queries: set[str] = set()
            for recipe in recipe_plan.get("recipes") if isinstance(recipe_plan.get("recipes"), list) else []:
                if not isinstance(recipe, dict):
                    continue
                for ingredient_query in recipe.get("ingredient_queries") if isinstance(recipe.get("ingredient_queries"), list) else []:
                    clean_query = str(ingredient_query).strip()
                    if clean_query and clean_query not in seen_queries:
                        seen_queries.add(clean_query)
                        ingredient_queries.append(clean_query)
            ingredient_results_by_query = {
                query: clubhx_tools_client.execute_canonical(
                    tenant_id=company_id,
                    tool="get_product_availability",
                    channel=channel,
                    user_id=user_id,
                    arguments={
                        "query": query,
                        "limit": 3,
                        "session_id": session_id,
                    },
                )
                for query in ingredient_queries[:8]
            }
            payload = _build_recipe_recommendation_payload(recipe_plan, ingredient_results_by_query)
            if payload:
                return payload

    cart_requests = _cart_requests_from_llm_intent(llm_commerce_intent)
    if cart_requests:
        _trace_route("commerce.cart_requests", session_id=session_id, requests=cart_requests)
        logger.warning(
            "commerce_router_cart_requests session_id=%s requests=%s",
            session_id,
            cart_requests,
        )
        canonical_results = [
            clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={
                    "query": str(cart_request.get("product_query") or "").strip(),
                    "limit": 5,
                    "session_id": session_id,
                },
            )
            for cart_request in cart_requests
        ]
        payload = _build_multi_cart_tool_payload(canonical_results, cart_requests)
        if payload:
            _trace_route(
                "commerce.resolve_multi_cart_payload",
                session_id=session_id,
                workflow_stage=str(payload.get("workflow_stage") or ""),
            )
            logger.warning(
                "commerce_router_resolved kind=multi_cart_payload session_id=%s workflow_stage=%s",
                session_id,
                str(payload.get("workflow_stage") or ""),
            )
            return payload

    lookup_queries = _product_lookup_queries_from_llm_intent(llm_commerce_intent)
    if len(lookup_queries) > 1:
        _trace_route("commerce.lookup_queries", session_id=session_id, queries=lookup_queries)
        logger.warning(
            "commerce_router_lookup_queries session_id=%s queries=%s",
            session_id,
            lookup_queries,
        )
        canonical_results = [
            clubhx_tools_client.execute_canonical(
                tenant_id=company_id,
                tool="get_product_availability",
                channel=channel,
                user_id=user_id,
                arguments={
                    "query": query,
                    "limit": 3,
                    "session_id": session_id,
                },
            )
            for query in lookup_queries
        ]
        payload = _build_multi_product_lookup_payload(canonical_results, lookup_queries, message, channel=channel)
        if payload:
            _trace_route(
                "commerce.resolve_multi_lookup_payload",
                session_id=session_id,
                products=len(payload.get("products") or []),
            )
            logger.warning(
                "commerce_router_resolved kind=multi_lookup_payload session_id=%s products=%s",
                session_id,
                len(payload.get("products") or []),
            )
            return payload

    _trace_route(
        "commerce.no_payload",
        session_id=session_id,
        greeting_like=_is_likely_greeting_message(message),
        normalized_message=normalized_message,
        llm_intent=str((llm_commerce_intent or {}).get("intent") or ""),
        lookup_queries=lookup_queries if 'lookup_queries' in locals() else [],
    )
    logger.warning(
        "commerce_router_no_payload session_id=%s greeting_like=%s normalized_message=%s llm_intent=%s lookup_queries=%s",
        session_id,
        _is_likely_greeting_message(message),
        normalized_message,
        str((llm_commerce_intent or {}).get("intent") or ""),
        lookup_queries if 'lookup_queries' in locals() else [],
    )
    return None
