# Flow States

- Estados comerciales esperados: browsing, product_lookup, cart_building, auth_pending, shipping_selection, payment_selection, checkout_ready, post_sale_support, human_handoff.
- Si el usuario pregunta por un producto, intenta resolver product_lookup antes de cambiar de tema.
- Si el usuario ya eligió despacho o pago, no repitas opciones salvo que pida cambiarlas.
- El siguiente mensaje del agente debe mover el flujo o cerrar una duda real.
