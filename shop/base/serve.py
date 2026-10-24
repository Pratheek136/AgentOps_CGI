"""Production entrypoint: single-process waitress server (one worker, threads)."""
import os

from waitress import serve

from app.main import create_app

if __name__ == "__main__":
    serve(create_app(), host="127.0.0.1", port=int(os.getenv("SHOP_PORT", "5000")),
          threads=8, ident="shop")
