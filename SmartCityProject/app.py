"""Entry point.  Local:  python app.py     Production (Azure/gunicorn):  gunicorn app:app"""
from smartcity import create_app
from smartcity.config import Config

app = create_app()

if __name__ == "__main__":
    # Flask's development server: fine for a local demo. debug is OFF unless FLASK_DEBUG=1.
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, use_reloader=False, threaded=True)
