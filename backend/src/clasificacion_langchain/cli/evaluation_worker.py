from __future__ import annotations

import os

os.environ.setdefault("EVAL_EMBEDDED_WORKER_ENABLED", "false")

from clasificacion_langchain.api.runtime import build_runtime
from clasificacion_langchain.operations.workers import evaluation_worker_loop, setup_services


def main() -> None:
    runtime = build_runtime()
    setup_services(
        chat_audit_service=runtime.chat_audit_service,
        retrieval_audit_service=runtime.retrieval_audit_service,
        agent_service=runtime.agent_service,
        evaluation_job_store=runtime.evaluation_job_store,
        evaluation_job_queue=runtime.evaluation_job_queue,
        tenancy_service=runtime.tenancy_service,
    )
    evaluation_worker_loop()


if __name__ == "__main__":
    main()
