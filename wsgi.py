"""
WSGI エントリーポイント (Flask版)
Gunicorn から呼び出されます
"""
from app import app

# Gunicorn が参照する application オブジェクト
application = app

if __name__ == "__main__":
    application.run()