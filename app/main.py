import logging

from .config import load_settings
from .scanner import Scanner


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    Scanner(settings).run()


if __name__ == "__main__":
    main()

