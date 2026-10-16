from pathlib import Path

from backend.app.app import create_app
from backend.app.cli import run

app = create_app(Path(__file__).parent.absolute())

if __name__ == "__main__":
    run(app)
