import random
import time
import logging
import json
import threading
from datetime import datetime
from chat_downloader import ChatDownloader
from pathlib import Path
import argparse

from cookies import convert_cookie_list_to_cookiejar, load_cookies
from recorder.streamlink_recorder import VideoRecorderThread, check_livestream

# 设置日志
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# 直播地址
TWITCH_URL = "https://www.twitch.tv/luoshushu0"
YOUTUBE_URL = "https://www.youtube.com/channel/UC7QVieoTCNwwW84G0bddXpA/live"

def retry_on_failure(max_retries=5, delay=2, exceptions=(Exception,)):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if i == max_retries - 1:
                        raise
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

class ChatDownloaderThread(threading.Thread):
    def __init__(self, url, filename, cookie=None):
        super().__init__()
        self.url = url
        self.filename = filename
        self._stop_event = threading.Event()
        if cookie:
            self.chat_downloader = ChatDownloader(cookies=';'.join([f"{k}={v}" for k, v in cookie.items()]) if isinstance(cookie, dict) else cookie)
        else:
            self.chat_downloader = ChatDownloader()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    @retry_on_failure(max_retries=3, delay=0.1)
    def run(self):
        try:
            # 确保输出目录存在
            Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
            
            chat = self.chat_downloader.get_chat(self.url)
            logging.info(f"开始下载聊天记录到 {self.filename}")
            with open(self.filename, 'a', encoding='utf-8') as f:
                for message in chat:
                    if self.stopped():
                        self.chat_downloader.close()
                        break

                    try:
                        json.dump(message, f, ensure_ascii=False)
                        f.write('\n')
                        f.flush()

                    except Exception as e:
                        logging.error(f"处理消息时出错: {str(e)}")
                        continue
            logging.info(f"聊天记录下载完成: {self.filename}")
        except Exception as e:
            logging.error(f"聊天下载失败: {str(e)}")
            raise e

def save_youtubecookies_from_browser(filename):
    cookies = load_cookies(None, ['chrome'])
    array_cookies = cookies.get_cookies_for_url(YOUTUBE_URL)
    convert_cookie_list_to_cookiejar(array_cookies).save(filename)
    
    logging.info(f"cookies {type(array_cookies[0])}")
    logging.info(f"成功保存cookies到 {filename}")

def main():
    parser = argparse.ArgumentParser(description="Monitor and record live streams from Twitch and YouTube.")
    parser.add_argument('--no-cookies', action='store_true', help="Do not use cookies for YouTube.")
    parser.add_argument('-s', '--save-cookies', action='store_true', help="Save YouTube cookies to file and exit.")
    parser.add_argument('-l', '--local-cookies', type=str, default='youtube_cookies.txt', dest='cookies_file', help="Special YouTube cookies file path.")
    parser.add_argument('--cookies-file-only', action='store_true', help="Only load cookies from the specified local file.")
    parser.add_argument('--debug', action='store_true', help="Set logging level to DEBUG.")
    args = parser.parse_args()

    # Set logging level to DEBUG if --debug is specified
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    youtube_video_thread = None
    twitch_video_thread = None
    youtube_chat_thread = None
    twitch_chat_thread = None
    
    output_dir = Path("recordings") / datetime.now().strftime("%Y%m%d")
    output_dir.mkdir(exist_ok=True)
    youtube_cookies_file = args.cookies_file
    youtube_cookies_dict = None

    if args.save_cookies:
        save_youtubecookies_from_browser(youtube_cookies_file)
        exit(0)

    def _load_cookies():
        nonlocal youtube_cookies_dict
        if not args.no_cookies:
            if args.cookies_file_only:
                logging.info(f"只从文件 {youtube_cookies_file} 加载cookies")
                array_cookies = load_cookies(youtube_cookies_file, None).get_cookies_for_url(YOUTUBE_URL)
            else:
                array_cookies = load_cookies(youtube_cookies_file, ['chrome']).get_cookies_for_url(YOUTUBE_URL)
                # update cookies file
                convert_cookie_list_to_cookiejar(array_cookies).save(youtube_cookies_file)
            youtube_cookies_dict = {cookie.name: cookie.value for cookie in array_cookies }
            if not youtube_cookies_dict:
                logging.error("请先登录YouTube")
                exit(1)

    _load_cookies()

    try:
        while True:
            try:
                if twitch_video_thread is None or not twitch_video_thread.is_alive():
                    logging.debug("检查Twitch直播状态")
                    is_twitch_live = check_livestream(TWITCH_URL)
                if not is_twitch_live and (youtube_video_thread is None or not youtube_video_thread.is_alive()):
                    logging.debug("检查YouTube直播状态")
                    is_youtube_live = check_livestream(YOUTUBE_URL, youtube_cookies_dict)
                
                # Twitch开播时
                if is_twitch_live and not twitch_video_thread:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    video_filename = output_dir / f"twitch_{timestamp}.ts"
                    chat_filename = output_dir / f"twitch_{timestamp}.json"
                    if twitch_video_thread is None or not twitch_video_thread.is_alive():
                        twitch_video_thread = VideoRecorderThread(TWITCH_URL, str(video_filename))
                        twitch_video_thread.start()
                    if twitch_chat_thread is None or not twitch_chat_thread.is_alive():
                        twitch_chat_thread = ChatDownloaderThread(TWITCH_URL, str(chat_filename))
                        twitch_chat_thread.start()
                    
                    # 如果YouTube在录制，则停止
                    if youtube_video_thread:
                        youtube_video_thread.stop()
                        youtube_video_thread.join(timeout=5)
                        youtube_video_thread = None
                        if youtube_chat_thread:
                            youtube_chat_thread.stop()
                            youtube_chat_thread.join(timeout=5)
                            youtube_chat_thread = None
                        logging.info("停止YouTube录制和聊天下载")
                
                # YouTube开播且Twitch未开播时
                elif is_youtube_live and not is_twitch_live:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    video_filename = output_dir / f"youtube_{timestamp}.ts"
                    chat_filename = output_dir / f"youtube_{timestamp}.json"
                    if youtube_video_thread is None or not youtube_video_thread.is_alive():
                        youtube_video_thread = VideoRecorderThread(YOUTUBE_URL, str(video_filename), youtube_cookies_dict)
                        youtube_video_thread.start()
                    if youtube_chat_thread is None or not youtube_chat_thread.is_alive():
                        youtube_chat_thread = ChatDownloaderThread(YOUTUBE_URL, str(chat_filename), youtube_cookies_file)
                        youtube_chat_thread.start()
                
            except Exception as e:
                logging.error(f"发生错误: {str(e)}")
            
            if is_youtube_live and not youtube_video_thread.is_alive():
                # 如果YouTube直播结束，重新加载cookies
                _load_cookies()
            # delay 1~7 second to check status
            time.sleep(random.randint(1, 7))
    except KeyboardInterrupt:
        logging.info("收到退出信号，正在清理...")
    finally:
        # 确保所有线程都被正确停止
        for thread in [youtube_video_thread, twitch_video_thread, 
                      youtube_chat_thread, twitch_chat_thread]:
            if thread:
                thread.stop()
                thread.join(timeout=5)

if __name__ == "__main__":
    logging.info("开始监控直播状态")
    main()
