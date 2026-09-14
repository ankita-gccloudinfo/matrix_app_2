# adhoc_report_sidecar — Phase 0 setup

Hosts the `abi/screenshot-to-code` backend as an internal-only service.
No `matrix_app/` file is touched by this phase — see `plan.md` Phase 0.

## Placement

Sibling of `matrix_app/`, same level as the `dynamic_report_maker/`
directory `dynamic_report_service.py` already expects:

```
your-workspace-root/
  matrix_app/
  dynamic_report_maker/
  adhoc_report_sidecar/      <- this directory
    docker-compose.yml
    .env                     <- create from .env.example, not committed
    screenshot-to-code/      <- clone goes here (step 1 below)
```

## Setup steps

1. Clone the upstream backend into this directory:
   ```bash
   cd adhoc_report_sidecar
   git clone --depth 1 https://github.com/abi/screenshot-to-code.git
   ```
2. Copy the env template and fill in the two values (copy from
   `matrix_app/.env` / `dynamic_report_service.py`'s `VLLM_BASE_URL` /
   `VLLM_API_KEY`):
   ```bash
   cp .env.example .env
   # edit .env
   ```
3. Build and start (backend only — the `docker-compose.yml` in this
   directory does not reference the upstream repo's own frontend service):
   ```bash
   docker compose up -d --build
   ```
4. Confirm it's up and can reach the vLLM endpoint:
   ```bash
   docker compose ps
   docker compose logs -f adhoc-html-backend
   curl http://127.0.0.1:7001/
   ```

## Exit criteria (per plan.md)

Can generate an HTML page from a raw prompt via this backend's own
WebSocket API (test with a standalone client — e.g. the upstream repo's
own frontend pointed at `ws://127.0.0.1:7001`, or a small test script),
with **zero changes made inside `matrix_app/`**.

Phase 1 (`services/adhoc_generation_service.py` inside `matrix_app/`) is
the first phase that adds any application code, and it depends on this
service already being reachable at `127.0.0.1:7001` from the same host.