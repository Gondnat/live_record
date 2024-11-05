import random
import streamlink
import time
import logging
import json
import threading
from datetime import datetime
from chat_downloader import ChatDownloader
from pathlib import Path
from recorder.youtube import YoutubeRecorderThread, check_youtube_live
from recorder.twitch import TwitchRecorderThread, check_twitch_live

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename
        self._stop_event = threading.Event()
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
            with open(self.filename, 'w', encoding='utf-8') as f:
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
        except Exception as e:
            logging.error(f"聊天下载失败: {str(e)}")
            raise e

def main():
    youtube_video_thread = None
    twitch_video_thread = None
    youtube_chat_thread = None
    twitch_chat_thread = None
    
    output_dir = Path("recordings")
    output_dir.mkdir(exist_ok=True)
    
    try:
        while True:
            try:
                twitch_live = check_twitch_live(TWITCH_URL)
                youtube_live = check_youtube_live(YOUTUBE_URL)
                
                # Twitch开播时
                if twitch_live and not twitch_video_thread:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    video_filename = output_dir / f"twitch_{timestamp}.ts"
                    chat_filename = output_dir / f"twitch_{timestamp}.json"
                    
                    logging.info("Twitch开播，开始录制视频和聊天")
                    twitch_video_thread = TwitchRecorderThread(TWITCH_URL, str(video_filename))
                    twitch_video_thread.start()
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
                elif youtube_live and not youtube_video_thread and not twitch_live:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    video_filename = output_dir / f"youtube_{timestamp}.%(ext)s"
                    chat_filename = output_dir / f"youtube_{timestamp}.%(ext)s"
                    
                    logging.info("YouTube开播，开始录制视频和聊天")
                    youtube_video_thread = YoutubeRecorderThread(YOUTUBE_URL, str(video_filename))
                    youtube_video_thread.start()
                    youtube_chat_thread = YoutubeRecorderThread(YOUTUBE_URL, str(chat_filename), True)
                    youtube_chat_thread.start()
                
                # Twitch关播时
                elif not twitch_live and twitch_video_thread:
                    twitch_video_thread.stop()
                    twitch_video_thread.join(timeout=5)
                    twitch_video_thread = None
                    if twitch_chat_thread:
                        twitch_chat_thread.stop()
                        twitch_chat_thread.join(timeout=5)
                        twitch_chat_thread = None
                    logging.info("Twitch关播，停止录制和聊天下载")
                
                # YouTube关播时
                elif not youtube_live and youtube_video_thread:
                    youtube_video_thread.stop()
                    youtube_video_thread.join(timeout=5)
                    youtube_video_thread = None
                    if youtube_chat_thread:
                        youtube_chat_thread.stop()
                        youtube_chat_thread.join(timeout=5)
                        youtube_chat_thread = None
                    logging.info("YouTube关播，停止录制和聊天下载")
                
            except Exception as e:
                logging.error(f"发生错误: {str(e)}")
                
            time.sleep(random.randint(7,17))
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
