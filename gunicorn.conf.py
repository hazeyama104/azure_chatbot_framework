workers = 1
worker_class = "aiohttp.GunicornWebWorker"
bind = "0.0.0.0:8000"
timeout = 600
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"