
import logging
import os
from pathlib import Path
from time import sleep, time

from bangumi.database import redisDB
from bangumi.downloader import DownloadItem, DownloadState, build_downloader, Downloader
from bangumi.parser import Parser
from bangumi.rss import RSS
from bangumi.util import Env, move_file

logger = logging.getLogger(__name__)


class Bangumi(object):

    def __init__(self) -> None:
        super().__init__()
        self.downloader: Downloader
        self.rss = RSS(urls=[
            # "https://dmhy.org/topics/rss/rss.xml"
            "https://mikanani.me/RSS/MyBangumi?token=2O6Rl47PH1mXSw6v3ACwCA%3d%3d"
        ])
        self.parser = Parser()

    def rename(self, item: DownloadItem) -> bool:
        logger.info(f"Renaming {item.id} {item.name}...")
        rss_item = redisDB.get(item.id)
        if not rss_item:
            logger.error(f"Can't find RSS item in Redis for {item.id}")
            return False
        if len(item.files) > 1:
            logger.error(f"Can't rename multi-file torrent {item.id}")
            return False
        if len(item.files) == 0:
            logger.error(f"Can't rename empty torrent {item.id}")
            return False

        file = item.files[0]

        if not file.exists():
            logger.error(f"File {file} doesn't exist")
            return False

        result = self.parser.analyse(rss_item.name)
        logger.info(f"Renaming {file.name} to {result.formatted}")
        try:
            move_file(file, result)
            return True
        except Exception as e:
            logger.error(f"Failed to rename {e}")
        return False

    def on_torrent_finished(self, item: DownloadItem):
        ret = self.rename(item)
        if not ret:
            return
        redisDB.remove(item.id)
        self.downloader.remove_torrent(item)

    def loop(self):

        def check():
            logger.info("Checking RSS...")
            last_t = redisDB.get_last_checked_time()
            items = self.rss.scrape(last_t)
            logger.info("Found %d items", len(items))
            for item in items:
                redisDB.set(item.hash, item)
                self.downloader.add_torrent(item.url)

        def check_complete():
            completed = self.downloader.get_downloads(DownloadState.FINISHED)
            if len(completed) == 0:
                return
            logger.info("Found %d completed downloads", len(completed))
            for item in completed:
                self.on_torrent_finished(item)

        INTERVAL = int(os.environ.get(Env.CHECK_INTERVAL.value, 60 * 10))

        while True:
            current = int(time())
            last = redisDB.get_last_checked_time()
            if current - last > INTERVAL:
                try:
                    check()
                except Exception as e:
                    logger.exception(e, stack_info=True)
                finally:
                    redisDB.update_last_checked_time()

            try:
                check_complete()
            except Exception as e:
                logger.exception(e, stack_info=True)

            sleep(10)

    def run(self):
        logger.info("Starting...")
        redisDB.connect()
        self.downloader = build_downloader()
        self.loop()
