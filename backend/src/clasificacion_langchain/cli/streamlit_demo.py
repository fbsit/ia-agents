from __future__ import annotations

from pathlib import Path

import streamlit as st

from clasificacion_langchain.shared.ml.inference_graph import build_inference_graph


def main() -> None:
    st.set_page_config(page_title="Clasificacion LangChain Demo", page_icon=":brain:")
    st.title("Demo: Clasificacion de Tweets")
    st.caption("LangChain + LangGraph + TF-IDF + LinearSVC")

    model_path = Path("backend/models/classifier.joblib")
    if not model_path.exists():
        st.error("No existe backend/models/classifier.joblib. Entrena primero con python -m clasificacion_langchain.cli.train_model")
        st.stop()

    graph = build_inference_graph(str(model_path))
    text = st.text_area("Escribi un texto:", value="hoy me siento frustrado con el servicio", height=120)
    if st.button("Clasificar", type="primary"):
        if not text.strip():
            st.warning("Ingresa texto para clasificar.")
        else:
            result = graph.invoke({"raw_text": text})
            st.subheader("Resultado")
            st.write(f"**Etiqueta:** {result.get('label', 'desconocido')}")
            st.write(f"**Confianza estimada:** {result.get('confidence', 0.0):.2%}")
            with st.expander("Detalle tecnico"):
                st.code(result.get("explanation", "sin detalle"), language="text")
                st.json(result.get("scores", {}))


if __name__ == "__main__":
    main()
