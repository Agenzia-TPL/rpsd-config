import os

worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
bind = "0.0.0.0:8000"
accesslog = "-"
errorlog = "-"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
