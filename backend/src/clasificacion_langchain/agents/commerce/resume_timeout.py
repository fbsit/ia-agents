from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from clasificacion_langchain.agents.commerce.state import WhatsAppCheckoutState


WorkflowDict = dict[str, str] | None
ClearMarkersFn = Callable[[], None]
PredicateFn = Callable[[str], bool]


@dataclass
class ResumeTimeoutResolution:
    payload: dict[str, object] | None
    handled: bool


def timeout_message() -> str:
    return "El proceso quedo pausado por inactividad. Si quieres retomarlo donde lo dejamos, responde 'si' dentro de 3 minutos. Si no, reinicio todo."


def workflow_state_has_active_checkout(workflow_state: WorkflowDict) -> bool:
    return any(
        str((workflow_state or {}).get(field) or "").strip()
        for field in {
            "stage",
            "checkout_stage",
            "pending_next_step",
            "awaiting_slot",
            "shipping_preference",
            "payment_preference",
            "pickup_location_label",
            "delivery_address",
            "invoice_type",
            "otp_email",
        }
    ) or str((workflow_state or {}).get("customer_authenticated") or "").strip().lower() in {"1", "true", "yes", "si"}


def describe_current_workflow(workflow_state: WorkflowDict) -> tuple[str, str, str, str]:
    current_stage = str((workflow_state or {}).get("stage") or "").strip().lower()
    current_checkout_stage = str((workflow_state or {}).get("checkout_stage") or "").strip().lower()
    current_pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip().lower()
    otp_email = str((workflow_state or {}).get("otp_email") or "").strip()
    selected_products = str((workflow_state or {}).get("selected_products") or "").strip()

    if not any([current_stage, current_checkout_stage, current_pending_next_step, otp_email]):
        return ("", "", "", "")

    if current_checkout_stage == "auth_pending" or current_pending_next_step in {"auth_pending", "auth_confirmation"}:
        return (
            "checkout_auth_needed",
            "checkout_ready",
            "auth_pending",
            "Estamos en la verificacion de acceso del pedido. Falta que me compartas tu correo para enviarte el codigo.",
        )
    if current_checkout_stage == "otp_pending" or current_pending_next_step == "otp_verification":
        email_hint = f" a {otp_email}" if otp_email else ""
        return (
            "checkout_otp_pending",
            "checkout_ready",
            "otp_pending",
            f"Estamos validando tu acceso al pedido. Falta que ingreses el codigo que te enviamos{email_hint}.",
        )
    if current_checkout_stage == "pickup_location_pending":
        return (
            "shipping_options",
            "shipping_selection",
            "pickup_location_pending",
            "Estamos definiendo el retiro del pedido. Falta que me digas en que tienda o punto quieres retirar.",
        )
    if current_checkout_stage in {"delivery_address_pending", "delivery_address_proposed"} or current_pending_next_step in {"delivery_address", "delivery_address_confirmation"}:
        return (
            "shipping_options",
            "shipping_selection",
            current_checkout_stage or "delivery_address_pending",
            "Estamos definiendo la direccion de despacho. Falta que me envies la direccion o confirmes la que ya te mostre.",
        )
    if current_checkout_stage == "shipping_method_pending" or current_pending_next_step == "shipping_selection":
        return (
            "shipping_options",
            "shipping_selection",
            "shipping_method_pending",
            "Estamos en el despacho del pedido. Falta que me digas si prefieres retiro en tienda o despacho.",
        )
    if current_checkout_stage in {"invoice_type_pending", "invoice_data_pending", "invoice_address_pending"} or current_pending_next_step in {"invoice_type", "invoice_data", "invoice_address"}:
        return (
            "invoice_type_pending",
            "payment_selection",
            current_checkout_stage or "invoice_type_pending",
            "Estamos completando los datos del documento. Falta definir si quieres boleta o factura.",
        )
    if current_checkout_stage == "order_summary_pending" or current_pending_next_step == "order_confirmation":
        product_hint = f" de {selected_products}" if selected_products else ""
        return (
            "order_summary_pending",
            "payment_selection",
            "order_summary_pending",
            f"Estamos revisando el resumen{product_hint}. Falta que me confirmes si esta todo correcto para seguir con el pago.",
        )
    if current_stage == "cart_building":
        product_hint = f" de {selected_products}" if selected_products else ""
        return (
            "cart_building",
            "cart_building",
            "",
            f"Estamos armando tu carrito{product_hint}. El siguiente paso es confirmar si quieres seguir comprando o pasar al checkout.",
        )
    if current_stage == "shipping_selection":
        return (
            "shipping_options",
            "shipping_selection",
            "shipping_method_pending",
            "Estamos definiendo el despacho del pedido. El siguiente paso es elegir entre retiro en tienda o despacho.",
        )
    if current_stage == "payment_selection":
        return (
            "payment_options",
            "payment_selection",
            "payment_method_pending",
            "Estamos en la etapa de pago del pedido. El siguiente paso es definir el documento y el medio de pago para poder avanzar.",
        )
    if current_stage == "checkout_ready":
        return (
            "checkout_ready",
            "checkout_ready",
            "",
            "Estamos en la parte final del checkout. El siguiente paso es retomar la confirmacion pendiente para cerrar el pedido.",
        )
    return (
        "workflow_in_progress",
        current_stage or "commerce",
        current_checkout_stage,
        "Tenemos un proceso en curso y podemos retomarlo desde donde lo dejamos.",
    )


def resolve_workflow_resume_followup(workflow_state: WorkflowDict) -> dict[str, object] | None:
    intent_label, workflow_stage, checkout_stage, description = describe_current_workflow(workflow_state)
    pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip()
    if description and (workflow_stage or checkout_stage or pending_next_step):
        return {
            "answer": f"Perfecto, retomamos tu pedido. {description}",
            "intent_label": intent_label,
            "workflow_stage": workflow_stage,
            "checkout_stage": checkout_stage,
            "pending_next_step": pending_next_step,
        }
    return None


def resolve_greeting_workflow_followup(
    *,
    message: str,
    workflow_state: WorkflowDict,
    is_greeting_message: PredicateFn,
) -> dict[str, object] | None:
    if not is_greeting_message(message):
        return None
    intent_label, workflow_stage, checkout_stage, description = describe_current_workflow(workflow_state)
    pending_next_step = str((workflow_state or {}).get("pending_next_step") or "").strip()
    if description and (workflow_stage or checkout_stage or pending_next_step):
        return {
            "answer": f"Hola. {description} Si quieres, seguimos desde ahi; si no, dime que quieres hacer y cambiamos de tema.",
            "intent_label": intent_label,
            "workflow_stage": workflow_stage,
            "checkout_stage": checkout_stage,
            "pending_next_step": pending_next_step,
        }
    return None


def resolve_legacy_preflight(
    *,
    message: str,
    workflow_state: WorkflowDict,
    clear_timeout_markers: ClearMarkersFn | None,
    is_affirmative_message: PredicateFn,
) -> ResumeTimeoutResolution:
    if str((workflow_state or {}).get("workflow_expired") or "").strip().lower() in {"1", "true", "yes", "si"}:
        return ResumeTimeoutResolution(
            payload={
                "answer": "El proceso anterior se reinicio por inactividad despues de 5 minutos. Arranquemos de nuevo: dime que necesitas.",
                "intent_label": "workflow_reset",
                "workflow_stage": "browsing",
                "checkout_stage": "",
                "pending_next_step": "",
                "reset_workflow": True,
            },
            handled=True,
        )
    timeout_confirmation = str((workflow_state or {}).get("workflow_timeout_confirmation") or "").strip().lower() in {"1", "true", "yes", "si"}
    if not timeout_confirmation:
        return ResumeTimeoutResolution(payload=None, handled=False)
    if is_affirmative_message(message):
        if clear_timeout_markers is not None:
            clear_timeout_markers()
        resumed_payload = resolve_workflow_resume_followup(workflow_state)
        if resumed_payload is not None:
            return ResumeTimeoutResolution(payload=resumed_payload, handled=True)
    return ResumeTimeoutResolution(
        payload={
            "answer": timeout_message(),
            "intent_label": "workflow_resume_confirmation",
            "workflow_stage": str((workflow_state or {}).get("stage") or "").strip() or "commerce",
            "checkout_stage": str((workflow_state or {}).get("checkout_stage") or "").strip(),
            "pending_next_step": str((workflow_state or {}).get("pending_next_step") or "").strip(),
        },
        handled=True,
    )


def resolve_resume_timeout_preflight(
    *,
    state: WhatsAppCheckoutState,
    clear_timeout_markers: ClearMarkersFn | None,
    is_affirmative_message: PredicateFn,
    is_greeting_message: PredicateFn,
) -> ResumeTimeoutResolution:
    workflow_state = state.to_workflow_state_dict()
    workflow_state["workflow_timeout_confirmation"] = "true" if state.workflow_timeout_confirmation else ""
    workflow_state["workflow_expired"] = "true" if state.workflow_expired else ""
    preflight = resolve_legacy_preflight(
        message=state.user_goal,
        workflow_state=workflow_state,
        clear_timeout_markers=clear_timeout_markers,
        is_affirmative_message=is_affirmative_message,
    )
    if preflight.handled:
        return preflight
    greeting_payload = resolve_greeting_workflow_followup(
        message=state.user_goal,
        workflow_state=workflow_state,
        is_greeting_message=is_greeting_message,
    )
    if greeting_payload is not None:
        return ResumeTimeoutResolution(payload=greeting_payload, handled=True)
    return ResumeTimeoutResolution(payload=None, handled=False)
