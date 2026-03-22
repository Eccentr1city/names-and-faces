import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("NAMES_AND_FACES_PORT", "5050"))
    app.run(debug=True, port=port)
