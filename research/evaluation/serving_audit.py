"""Measure a local multithreaded HTTP server against an isolated PostgreSQL test DB."""

import argparse
import json
import os
import platform
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from threadpoolctl import threadpool_limits


def run(output):
    import django

    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler, get_internal_wsgi_application
    from django.db import connections
    from django.test import Client, override_settings
    from django.test.utils import setup_databases, teardown_databases

    from apps.catalog.models import Category, Product, ProductCategory
    from apps.recommendations.services import active_bundle
    from research.data.dataset import ResearchDataset
    from research.data.io import write_json

    output = Path(output)
    if output.exists():
        raise ValueError("Use a fresh result file")
    config = setup_databases(verbosity=0, interactive=False)
    server = None
    try:
        rows = list(ResearchDataset("data/processed/amazon-medium-v1").rows("catalog"))
        Product.objects.bulk_create([
            Product(external_item_id=row["item_id"], name=row["title"][:600], slug=f"item-{row['item_id'].lower()}",
                    price=99000, stock=20, is_active=True) for row in rows
        ])
        category = Category.objects.create(name="Phụ kiện điện thoại", slug="accessories")
        ProductCategory.objects.bulk_create([ProductCategory(product=product, category=category) for product in Product.objects.all()])
        user = get_user_model().objects.create_user(username="audit-new-customer", password="test-password")
        client = Client()
        client.force_login(user)
        cookie = "; ".join(f"{key}={value.value}" for key, value in client.cookies.items())
        bundle, manifest = active_bundle()
        first = Product.objects.first()

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, format, *args):
                pass

        with override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"]):
            server = ThreadedWSGIServer(("127.0.0.1", 0), QuietHandler, allow_reuse_address=False)
            server.set_app(get_internal_wsgi_application())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            endpoints = ["/", "/san-pham/", f"/san-pham/{first.slug}/"]

            def request(path):
                started = time.perf_counter()
                try:
                    with urlopen(Request(base + path, headers={"Cookie": cookie}), timeout=30) as response:
                        body = response.read()
                        return response.status, 1000 * (time.perf_counter() - started), len(body)
                except Exception as error:
                    return type(error).__name__, 1000 * (time.perf_counter() - started), 0

            for endpoint in endpoints:
                request(endpoint)
            measurements = []
            for concurrency in [1, 5, 10]:
                for endpoint in endpoints:
                    started = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        results = list(pool.map(request, [endpoint] * 30))
                    elapsed = time.perf_counter() - started
                    durations = [result[1] for result in results]
                    measurements.append({
                        "endpoint": endpoint, "concurrency": concurrency, "requests": len(results),
                        "statuses": Counter(str(result[0]) for result in results),
                        "median_ms": float(np.median(durations)), "p95_ms": float(np.percentile(durations, 95)),
                        "requests_per_second": len(results) / elapsed,
                    })
            write_json(output, {
                "scope": "HTTP response and HTML body, authenticated cold-start user, local ThreadedWSGIServer, warm artifact cache; excludes images, browser rendering, Internet and production deployment",
                "database": "isolated PostgreSQL test database, created and removed for this run",
                "products": len(rows), "model": manifest["model_version"],
                "platform": platform.platform(), "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                "measurements": measurements,
            })
    finally:
        if server:
            server.shutdown()
            server.server_close()
        connections.close_all()
        teardown_databases(config, verbosity=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        run(args.output)
    print("Local HTTP measurements saved")
