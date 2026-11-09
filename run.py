"""누리 실행: python run.py  (브라우저에서 http://127.0.0.1:8780)"""
import socket
import sys
import threading
import webbrowser

import uvicorn

from app.core import cfg

if __name__ == "__main__":
    host, port = cfg.get("host", "127.0.0.1"), int(cfg.get("port", 8780))
    if host not in ("127.0.0.1", "localhost") and not cfg.get("pin"):
        print("[주의] 다른 기기 접속(host=0.0.0.0)은 PIN을 설정해야 켜져요. 이 컴퓨터에서만 열게요.")
        host = "127.0.0.1"
    if host == "0.0.0.0":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            print(f"같은 와이파이의 폰/태블릿에서: http://{s.getsockname()[0]}:{port}")
        except OSError:
            pass
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run("app.main:app", host=host, port=port, log_level="warning")
