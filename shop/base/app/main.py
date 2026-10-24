"""Demo shop: /products, /cart, /checkout, /health, /metrics."""
import os
import time
import traceback
import uuid

import psutil
from flask import Flask, g, jsonify, request

from . import catalog, pricing
from .payment import PaymentClient, PaymentError
from .settings import load_config
from .telemetry import JsonLogger, Metrics
from .version import git_short_sha

TRACKED = {"/products", "/cart", "/checkout"}


def create_app(config: dict[str, str] | None = None) -> Flask:
    app = Flask(__name__)
    cfg = config if config is not None else load_config()
    payments = PaymentClient(cfg)
    metrics = Metrics()
    logger = JsonLogger()
    version = git_short_sha()
    started = time.time()
    proc = psutil.Process(os.getpid())

    @app.before_request
    def _start() -> None:
        g.t0 = time.perf_counter()
        g.order_id = None
        g.order_value = None

    @app.after_request
    def _finish(resp):
        if request.path in TRACKED:
            latency = (time.perf_counter() - g.t0) * 1000
            metrics.record(request.path, resp.status_code, latency)
            if resp.status_code < 500:
                logger.log("INFO", "request ok", endpoint=request.path, status=resp.status_code,
                           latency_ms=round(latency, 1), order_id=g.order_id,
                           order_value_inr=g.order_value)
        return resp

    def _error(exc: Exception, status: int = 500):
        latency = (time.perf_counter() - g.t0) * 1000
        logger.log("ERROR", str(exc), endpoint=request.path, status=status,
                   latency_ms=round(latency, 1), order_id=g.order_id,
                   order_value_inr=g.order_value, error_type=type(exc).__name__,
                   traceback=traceback.format_exc())
        return jsonify({"error": type(exc).__name__, "message": str(exc)}), status

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "version": version})

    @app.get("/products")
    def products():
        return jsonify({"products": list(catalog.list_products())})

    @app.post("/cart")
    def cart():
        body = request.get_json(force=True, silent=True) or {}
        try:
            total = pricing.subtotal(body.get("items", []))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"subtotal_inr": total})

    @app.post("/checkout")
    def checkout():
        body = request.get_json(force=True, silent=True) or {}
        g.order_id = body.get("order_id") or f"ord_{uuid.uuid4().hex[:10]}"
        try:
            amount = pricing.subtotal(body.get("items", []))
            coupon = pricing.lookup_coupon(body.get("coupon"))
            total = pricing.apply_discount(amount, coupon)
            g.order_value = total
            txn = payments.charge(total, g.order_id)
        except (ConnectionError, PaymentError) as exc:
            g.order_value = g.order_value or body.get("expected_value_inr")
            return _error(exc, 502 if isinstance(exc, ConnectionError) else 503)
        except Exception as exc:  # noqa: BLE001 - surface as 500 with traceback
            g.order_value = g.order_value or body.get("expected_value_inr")
            return _error(exc, 500)
        return jsonify({"order_id": g.order_id, "total_inr": total, "txn": txn})

    @app.get("/metrics")
    def metrics_view():
        return jsonify({
            "version": version,
            "uptime_s": round(time.time() - started, 1),
            "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
            "endpoints": metrics.snapshot(),
            "total_requests": metrics.total_requests,
            "total_errors": metrics.total_errors,
        })

    return app
