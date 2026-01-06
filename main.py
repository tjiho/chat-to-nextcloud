import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from src.adapters.base import BaseAdapter
from src.adapters.matrix import MatrixAdapter, MatrixAuthError
from src.adapters.telegram import TelegramAdapter
from src.config import Config
from src.file_processor import FileProcessor
from src.uploader import DryRunUploader, NextcloudUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload files from messaging apps to Nextcloud"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be uploaded without actually uploading",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging (show all messages)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config file (default: config.yaml)",
    )
    return parser.parse_args()


async def run_adapter(
    adapter: BaseAdapter,
    processor: FileProcessor,
    stop_event: asyncio.Event,
) -> None:
    try:
        await adapter.connect()
        logger.info(f"Started {adapter.platform_name} adapter")

        async for file_message in adapter.listen():
            await processor.process_file(adapter, file_message)

    except MatrixAuthError as e:
        logger.error(f"\n{'='*60}\nMatrix Authentication Error:\n{'='*60}\n{e}\n{'='*60}")
        stop_event.set()
    except asyncio.CancelledError:
        logger.info(f"Stopping {adapter.platform_name} adapter")
    except Exception as e:
        logger.error(f"Unexpected error in {adapter.platform_name} adapter: {e}")
        stop_event.set()
    finally:
        await adapter.disconnect()


async def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger("src").setLevel(logging.DEBUG)
        logger.info("Verbose mode enabled")

    if not args.config.exists():
        logger.error(f"{args.config} not found. Copy config.yaml.example and configure it.")
        sys.exit(1)

    config = Config.load(args.config)

    if args.dry_run:
        logger.info("Running in DRY-RUN mode - no files will be uploaded")
        uploader = DryRunUploader(config.nextcloud)
    else:
        uploader = NextcloudUploader(config.nextcloud)

    if not uploader.check_connection():
        logger.warning("Could not verify Nextcloud connection. Will retry on upload.")

    processor = FileProcessor(uploader, config.path_template)

    adapters: list[BaseAdapter] = []

    if config.adapters.matrix:
        adapters.append(MatrixAdapter(config.adapters.matrix))

    if config.adapters.telegram:
        adapters.append(TelegramAdapter(config.adapters.telegram))

    if not adapters:
        logger.error("No adapters enabled in configuration")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    tasks = [
        asyncio.create_task(run_adapter(adapter, processor, stop_event))
        for adapter in adapters
    ]

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await stop_event.wait()

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
