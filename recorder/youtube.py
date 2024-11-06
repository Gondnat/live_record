import logging
from pathlib import Path
import threading
import yt_dlp

class YoutubeRecorderThread(threading.Thread):
    def __init__(self, url, filename, download_chat=False, cookie_browsers=['chrome']) :
        super().__init__()
        self.url = url
        self.filename = filename
        self.download_chat = download_chat
        self.cookie_browsers = cookie_browsers
        self._stop_event = threading.Event()
        self.process = None
        
    def stop(self):
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
        
    def stopped(self):
        return self._stop_event.is_set()
        
    def run(self):
        try:
            # 确保输出目录存在
            Path(self.filename).parent.mkdir(parents=True, exist_ok=True)

            ydl_opts = {
                'outtmpl': self.filename,
                'quiet': True,
                'no_warnings': True,
                'cookiesfrombrowser': self.cookie_browsers,
                # 'live_from_start': True, # Not work with format best
                # 'format': 'best', # 优先下载视频
            }

            if self.download_chat:
                ydl_opts = {**ydl_opts, ** {'subtitleslangs': ['live_chat'],'writesubtitles': True,}}
                logging.info(f"开始下载YouTube实时聊天: {self.url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.process = ydl.download([self.url])
                
        except Exception as e:
            if self.download_chat:
                logging.error(f"YouTube实时聊天下载失败:{str(e)}")
            else:
                logging.error(f"YouTube视频录制失败: {str(e)}")
        finally:
            if self.process:
                try:
                    self.process.terminate()
                except:
                    pass


def check_youtube_live(url, cookie_browsers=['chrome']):
    """检查YouTube直播状态"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': cookie_browsers,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('is_live', False)
    except Exception as e:
        logging.error(f"Error checking YouTube live status: {str(e)}")
        return False

# def check_youtube_live(url, cookie_browsers=['chrome']):
#     """检查YouTube直播状态"""
#     try:
#         ydl_opts = {
#             'quiet': True,
#             'no_warnings': True,
#             'cookiesfrombrowser': cookie_browsers,
#         }
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             info = ydl.extract_info(url, download=False)
#             return info.get('is_live', False)
#     except:
#         return False
