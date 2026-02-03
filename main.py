import subprocess
import time
import sys

def start_services():
    print("--- 正在启动 TG 按需登录系统 ---")
     # 启动 Worker 扫描器
    worker_proc = subprocess.Popen([sys.executable, "worker.py"])
    print("✅ Worker 扫描器已在后台启动")
    
    # 启动 API 服务
    api_proc = subprocess.Popen([sys.executable, "api.py"])
    print("✅ API 服务已在后台启动 (Port 8000)")
    
   
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭服务...")
        api_proc.terminate()
        worker_proc.terminate()

if __name__ == "__main__":
    start_services()