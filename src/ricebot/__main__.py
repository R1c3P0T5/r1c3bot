from ricebot.bot import run
from ricebot.config import Config, ConfigError


def main() -> None:
    try:
        config = Config.from_env()
    except ConfigError as error:
        raise SystemExit(f"ricebot: {error}") from error
    run(config)


if __name__ == "__main__":
    main()
