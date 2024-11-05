import logging
from pathlib import Path
import threading
import streamlink

def check_twitch_live(url):
    """检查Twitch直播状态"""
    try:
        streams = streamlink.streams(url)
        return len(streams) > 0
    except:
        return False

class TwitchRecorderThread(threading.Thread):
    def __init__(self, url, filename, quality='best'):
        super().__init__()
        self.url = url
        self.filename = filename
        self.quality = quality
        self._stop_event = threading.Event()
        self.stream_fd = None
        self.output_fd = None
        
    def stop(self):
        self._stop_event.set()
        if self.stream_fd:
            try:
                self.stream_fd.close()
            except:
                pass
        if self.output_fd:
            try:
                self.output_fd.close()
            except:
                pass
        
    def stopped(self):
        return self._stop_event.is_set()
        
    def run(self):
        try:
            streams = streamlink.streams(self.url)
            if not streams:
                logging.error(f"无法获取Twitch直播流: {self.url}")
                return
                
            stream = streams[self.quality]
            Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
            
            self.stream_fd = stream.open()
            self.output_fd = open(self.filename, 'wb')
            
            while not self.stopped():
                try:
                    data = self.stream_fd.read(1024*1024)
                    if not data:
                        break
                    self.output_fd.write(data)
                except Exception as e:
                    logging.error(f"Twitch录制过程中出错: {str(e)}")
                    break
                    
        except Exception as e:
            logging.error(f"Twitch视频录制失败: {str(e)}")
        finally:
            if self.stream_fd:
                try:
                    self.stream_fd.close()
                except:
                    pass
            if self.output_fd:
                try:
                    self.output_fd.close()
                except:
                    pass
