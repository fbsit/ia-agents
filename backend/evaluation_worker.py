from __future__ import annotations

import os


# Evita iniciar worker embebido al importar chat_api en este proceso dedicado.
os.environ.setdefault("EVAL_EMBEDDED_WORKER_ENABLED", "false")

from chat_api import run_evaluation_worker_forever


def main() -> None:
    run_evaluation_worker_forever()


if __name__ == "__main__":
    main()
