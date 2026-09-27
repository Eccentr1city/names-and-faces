import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("NAMES_AND_FACES_PORT", "5050"))
    host = os.environ.get("NAMES_AND_FACES_HOST", "127.0.0.1")
    debug = os.environ.get("NAMES_AND_FACES_DEBUG", "1") == "1"
    app.run(debug=debug, host=host, port=port)
