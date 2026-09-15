from __future__ import annotations

import json


def build_commerce_intent_messages(
    *,
    message: str,
    intent_label_hint: str,
    channel: str,
    response_style_context: str,
    workflow_context: str,
    recent_products: list[dict[str, object]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Eres un planner de workflow comercial para un agente conversacional de e-commerce. "
                "Debes detectar la intencion, decidir si conviene responder con texto, pedir aclaracion o ejecutar un tool, "
                "y definir la forma de responder de manera breve, comercial y accionable. "
                "Devuelve SOLO JSON valido con esta forma exacta: "
                "{\"intent\":string,\"confidence\":number,\"query\":string,\"items\":[{\"query\":string,\"quantity\":number}],\"tool\":string,\"tool_arguments\":object,\"needs_clarification\":boolean,\"clarification_question\":string,\"customer_goal\":string,\"response_style\":{\"stage\":string,\"tone\":string,\"next_step\":string,\"format\":string}}. "
                "Intent permitidos: none, product_lookup, add_to_cart, remove_from_cart, set_cart_quantity, clear_cart, cart_status, shipping_options, payment_options, order_status, create_payment_link, create_order_draft, recipe_recommendation. "
                "Tools permitidos: none, get_product_availability, get_order_status, get_shipping_options, get_payment_options, create_payment_link, create_order_draft. "
                "Usa el workflow_context como prioridad para interpretar la intencion. Si workflow_context indica checkout_stage=auth_pending, el mensaje actual debe tratarse como un correo para enviar el codigo. Si checkout_stage=otp_pending, el mensaje actual debe tratarse como el valor a verificar con verify_verification_code usando otp_email persistido. "
                "Extrae productos y cantidades solo cuando el usuario lo exprese de forma clara en el mensaje y en contexto de compra. Si no hay cantidad explicita usa 1. "
                "Si pide quitar unidades del carrito usa remove_from_cart. Si pide dejar una cantidad exacta usa set_cart_quantity. Si pide vaciar el carrito usa clear_cart. Si pregunta por el carrito actual, resumen del carrito o como va el carrito, usa cart_status y NO order_status. "
                "Si el mensaje pregunta disponibilidad, precio, stock o catalogo usa get_product_availability. "
                "Si pregunta estado de pedido usa get_order_status y extrae order_reference cuando exista. "
                "Si quiere pagar ahora o generar link usa create_payment_link solo si ya hay productos/orden suficientes, si no pide el dato faltante. "
                "Si quiere cerrar pedido, reservar o generar borrador usa create_order_draft solo si hay items claros. "
                "Si pregunta medios de pago usa get_payment_options. Si pregunta despacho, envio o retiro usa get_shipping_options. "
                "Si el mensaje usa referencias como 'agregamelo', 'ese', 'el primero', 'el segundo', debes resolverlas usando recent_products si existe contexto. "
                "Si el usuario responde solo con una cantidad como '1', '2' o 'quiero 1' luego de ver un producto o un listado, interpretalo como seguimiento de compra y usa recent_products o workflow_context para decidir add_to_cart o set_cart_quantity. "
                "No inventes datos faltantes. Si faltan datos criticos marca needs_clarification=true y escribe clarification_question concreta."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "message": message,
                    "intent_label_hint": intent_label_hint,
                    "channel": channel,
                    "response_style_context": response_style_context,
                    "workflow_context": workflow_context,
                    "recent_products": recent_products,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_invoice_extraction_messages(message: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Eres un extractor de datos de facturacion para e-commerce chileno. "
                "Del mensaje del usuario extrae SOLO datos de facturacion. "
                "Devuelve SOLO JSON valido con estos campos:\n"
                "{\n"
                '  "invoice_type": "factura" | "boleta" | null,\n'
                '  "rut": "RUT chileno formateado" | null,\n'
                '  "business_name": "razon social o nombre empresa" | null,\n'
                '  "invoice_address": "direccion fiscal" | null,\n'
                '  "use_delivery_address": true | false\n'
                "}\n\n"
                "Reglas:\n"
                "- invoice_type: 'factura' si pide facturar, 'boleta' si dice boleta o no menciona tipo\n"
                "- RUT: formato XX.XXX.XXX-X o XXXXXXXXX-X, extraer aunque vaya pegado\n"
                "- business_name: razon social, nombre de empresa, o persona juridica\n"
                "- invoice_address: direccion fiscal solo si la da explicitamente\n"
                "- use_delivery_address: true SOLO si el usuario confirma usar la direccion de despacho cuando se le pregunta (dice 'si', 'la misma', 'igual', 'confirmo'). false en caso contrario.\n"
                "- Cualquier campo que no aparezca en el mensaje debe ir como null.\n"
                "- No inventes datos."
            ),
        },
        {"role": "user", "content": message},
    ]


def build_recipe_plan_messages(
    *,
    message: str,
    recent_product_names: list[str],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Eres un planificador de recetas para e-commerce. "
                "Devuelve SOLO JSON con esta forma exacta: "
                "{\"recipes\":[{\"name\":string,\"reason\":string,\"ingredient_queries\":[string]}]}. "
                "Sugiere maximo 2 recetas. Usa ingredientes buscables en un catalogo de supermercado. "
                "Si el usuario pide una receta especifica como queque, priorizala. "
                "Si menciona hambre o cocinar, propone recetas simples. "
                "Si hay productos recientes del historial, usalos como contexto para priorizar recetas relacionadas."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "message": message,
                    "recent_products": recent_product_names[:8],
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_checkout_planner_context(
    *,
    workflow_stage: str,
    checkout_stage: str,
    pending_next_step: str,
    otp_email: str,
) -> str:
    return (
        f"stage={workflow_stage};"
        f"checkout_stage={checkout_stage};"
        f"pending_next_step={pending_next_step};"
        f"otp_email={otp_email}"
    )
