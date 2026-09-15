# Promoted Learning Memory

- La frase "tienen X" debe interpretarse como consulta de disponibilidad o catálogo.
- La frase "cuánto cuesta X" debe interpretarse como consulta comercial de producto.
- Si el usuario dice "agrega/agregar/pon/suma/llevo N PRODUCTO al carrito", debe interpretarse como intencion add_to_cart, no checkout.
- La palabra "carrito" por si sola no debe forzar login ni checkout si la frase principal describe agregar un producto con cantidad.
- Si el usuario pregunta por retiro, envío, comuna o Chilexpress, prioriza el flujo de despacho.
- Si el usuario pregunta por transferencia, tarjeta o Mercado Pago, prioriza el flujo de medios de pago.
- En web, cuando el usuario ya mostró intención de compra, la respuesta debe empujar a carrito o checkout.
- En WhatsApp, cuando el usuario ya eligió una opción válida, la respuesta debe avanzar de etapa y no reiniciar el flujo.
