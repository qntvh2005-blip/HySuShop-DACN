"""HTTP load with separate initial-history cohorts on an isolated PostgreSQL database."""

import argparse
import json
import os
import platform
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from threadpoolctl import threadpool_limits


def run(output):
    import django
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler, get_internal_wsgi_application
    from django.db import connections
    from django.db.models import Count
    from django.test import Client, override_settings
    from django.test.utils import setup_databases, teardown_databases
    from apps.catalog.models import Product
    from apps.interactions.models import UserInteraction
    from apps.recommendations.models import RecommendationLog
    from apps.recommendations.services import active_bundle
    from research.data.io import write_json

    output = Path(output)
    if output.exists():
        raise ValueError("Use a fresh result file")
    config = setup_databases(verbosity=0, interactive=False)
    server = None
    try:
        call_command("import_research_catalog", "data/processed/amazon-medium-v1", verbosity=0)
        Product.objects.update(price=99000, stock=20, is_active=True)
        products = list(Product.objects.order_by("external_item_id"))
        bundle, manifest = active_bundle()
        cohorts = {}
        for label, size in [("new", 0), ("short", 3), ("long", 20)]:
            accounts = []
            for i in range(10):
                user = get_user_model().objects.create_user(username=f"load-{label}-{i}")
                client = Client();client.force_login(user)
                cookie = "; ".join(f"{key}={value.value}" for key, value in client.cookies.items())
                accounts.append((user.pk, cookie))
            cohorts[label] = (size, accounts)
        def seed_history(label):
            # Only the isolated test DB is modified. Reset before every measured route phase.
            UserInteraction.objects.all().delete()
            size, accounts = cohorts[label]
            UserInteraction.objects.bulk_create([
                UserInteraction(user_id=user, product=product, event_type="view")
                for user, _ in accounts for product in products[:size]
            ])
            assert UserInteraction.objects.count() == size * len(accounts)

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, format, *args):
                pass
        with override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"]):
            server = ThreadedWSGIServer(("127.0.0.1", 0), QuietHandler, allow_reuse_address=False)
            server.set_app(get_internal_wsgi_application())
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            endpoints = ["/", "/san-pham/", f"/san-pham/{products[0].slug}/"]
            measurements = []
            for label, (size, accounts) in cohorts.items():
                def request(args):
                    endpoint, cookie = args;started = time.perf_counter()
                    try:
                        with urlopen(Request(base + endpoint, headers={"Cookie": cookie}), timeout=30) as response:
                            body = response.read()
                            return response.status, 1000 * (time.perf_counter() - started), len(body)
                    except HTTPError as error:
                        return error.code, 1000 * (time.perf_counter() - started), 0
                    except Exception as error:
                        return type(error).__name__, 1000 * (time.perf_counter() - started), 0
                for concurrency in [1, 5, 10, 20]:
                    for endpoint in endpoints:
                        seed_history(label)
                        request((endpoint, accounts[0][1]))
                        seed_history(label)  # Detail warm-up adds a view; remove it before measurement.
                        RecommendationLog.objects.all().delete()
                        started = time.perf_counter()
                        with ThreadPoolExecutor(max_workers=concurrency) as pool:
                            results = list(pool.map(request, [(endpoint, accounts[i % len(accounts)][1]) for i in range(40)]))
                        elapsed = time.perf_counter() - started
                        logs = list(RecommendationLog.objects.values("algorithm", "fallback_reason").annotate(count=Count("id")).order_by("algorithm", "fallback_reason"))
                        if label == "new" and endpoint == "/":
                            assert all(row["fallback_reason"] == "no_known_history" for row in logs)
                        measurements.append({"cohort": label, "initial_known_events": size,
                            "endpoint": endpoint, "concurrency": concurrency, "requests": len(results),
                            "statuses": Counter(str(r[0]) for r in results),
                            "median_ms": float(np.median([r[1] for r in results])),
                            "p95_ms": float(np.percentile([r[1] for r in results], 95)),
                            "requests_per_second": len(results) / elapsed, "served_algorithms": logs})
                        print(label, concurrency, endpoint, measurements[-1]["statuses"], flush=True)
            write_json(output, {"scope": "local HTML only; full imported research metadata and image URL records; simulated price=99000 and stock=20 for all 709 products; ten accounts per cohort; view-only profiles of 0/3/20 known items reset before each route phase; detail requests add views during their phase; same-route phases, not a mixed navigation journey; warm cache; no images/network/browser rendering/production or customer study",
                "model": manifest["model_version"], "cohorts": 3, "accounts_per_cohort": 10,
                "products": len(products), "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                "measurements": measurements})
    finally:
        if server:
            server.shutdown();server.server_close()
        connections.close_all();teardown_databases(config, verbosity=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
