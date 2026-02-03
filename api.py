from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
import redis, os, uvicorn, io, asyncio

# ======== 配置区 ========
# 支持通过环境变量配置以便容器化部署
REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
VALID_TOKENS = [os.environ.get('ADMIN_TOKEN', 'y5JEKbVRcPHde59y')] # 你的万能登录密钥
SALT = int(os.environ.get('SALT', 1234567890))
SESSION_DIR = os.environ.get('SESSION_DIR', 'sessions')
BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:8000')
DEFAULT_2FA = os.environ.get('DEFAULT_2FA', 'bz666')

if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)
# ========================

app = FastAPI()

# --- 权限校验助手 ---
def verify_user(request: Request):
    """从 Cookie 中读取 token 并验证"""
    token = request.cookies.get("admin_token")
    if token in VALID_TOKENS:
        return token
    return None

def encode_phone(p): return hex(int(p) + SALT)[2:]
def decode_phone(h): return str(int(h, 16) - SALT)

# --- 1. 登录入口 ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if verify_user(request): return RedirectResponse(url="/admin")
    return """
    <html><head><title>TG管理系统登录</title>
    <style>
        body { font-family:sans-serif; background:#f4f7f9; display:flex; justify-content:center; align-items:center; height:100vh; margin:0; }
        .card { background:white; padding:40px; border-radius:15px; box-shadow:0 10px 25px rgba(0,0,0,0.1); width:320px; text-align:center; }
        h2 { color: #333; margin-bottom: 20px; }
        input { width:100%; padding:12px; margin-bottom:20px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; outline:none; }
        input:focus { border-color: #0088cc; }
        button { width:100%; padding:12px; background:#0088cc; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:bold; }
        button:hover { background:#0077b3; }
    </style></head>
    <body><div class="card">
        <h2>后台身份验证</h2>
        <input type="password" id="pw" placeholder="请输入 Token 密钥" onkeydown="if(event.keyCode==13) doLogin()">
        <button onclick="doLogin()">一键登录</button>
    </div>
    <script>
        async function doLogin() {
            let pw = document.getElementById('pw').value;
            let res = await fetch(`/auth?token=` + pw);
            let data = await res.json();
            if(data.status === 'ok') location.href = '/admin';
            else alert('Token 无效，请重新输入');
        }
    </script></body></html>
    """

@app.get("/auth")
async def auth_endpoint(token: str, response: Response):
    if token in VALID_TOKENS:
        # 设置 7 天有效期 (604800秒)
        response.set_cookie(key="admin_token", value=token, max_age=604800, httponly=True)
        return {"status": "ok"}
    return {"status": "error"}

# --- 2. 管理后台 (核心适配) ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, page: int = 1, size: int = 10):
    token = verify_user(request)
    if not token: return RedirectResponse(url="/")
    
    # 1. 获取所有文件并排序（确保分页顺序稳定）
    all_files = sorted([f for f in os.listdir(SESSION_DIR) if f.endswith('.session')])
    total_count = len(all_files)
    
    # 2. 计算分页切片
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    files_to_show = all_files[start_idx:end_idx]
    
    # 3. 计算总页数
    total_pages = (total_count + size - 1) // size
    if total_pages == 0: total_pages = 1

    rows = ""
    for idx, f in enumerate(files_to_show, start=start_idx + 1):
        p = f.replace('.session', '')
        h = encode_phone(p)
        login_val = r.get(f"tg_login_status:{p}")
        login_status = '<span style="color:#2ecc71;">已登录</span>' if login_val == b"1" else '<span style="color:#e74c3c;">未登录</span>'
        code_status = ' <b style="color:#0088cc;">[有码]</b>' if r.exists(f"tg_code:{p}") else ' [等待]'
        current_2fa = (r.get(f"tg_2fa:{p}") or DEFAULT_2FA.encode()).decode()

        rows += f"""
        <tr>
            <td><input type='checkbox' class='sel' value='{p}'></td>
            <td>{idx}</td>
            <td>{p}</td>
            <td>{current_2fa}</td>
            <td>{login_status}{code_status}</td>
            <td>
                <button onclick="changePW('{p}', '{login_val.decode() if login_val else '0'}')">改密</button>
                <button onclick="control('{p}', 'start')" style="background:#27ae60;color:white;border:none;">登录</button>
                <button onclick="control('{p}', 'logout')" style="background:#95a5a6;color:white;border:none;">断开</button>
                <button onclick="deleteConfirm('{p}')" style="background:#e74c3c;color:white;border:none;">删除</button>
            </td>
            <td><a href="/{h}/GetHTML" target="_blank" style="color:#0088cc;text-decoration:none;">查看API</a></td>
        </tr>"""

    # 4. 预备每页数量的选项
    size_options = ""
    for s in [10, 20, 30, 50]:
        selected = "selected" if s == size else ""
        size_options += f'<option value="{s}" {selected}>{s}条/页</option>'

    return f"""
    <html><head><title>TG管理后台</title>
    <style>
        body {{ font-family:sans-serif; background:#f4f7f9; padding:20px; }}
        .card {{ background:white; padding:20px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.05); margin-bottom:20px; }}
        table {{ width:100%; border-collapse:collapse; background:white; }}
        th {{ background:#0088cc; color:white; padding:12px; text-align:left; }}
        td {{ padding:12px; border-bottom:1px solid #eee; }}
        button {{ padding:6px 12px; border-radius:4px; border:1px solid #ccc; cursor:pointer; margin-right:5px; font-size:12px; }}
        .batch-bar {{ margin-bottom: 15px; display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
        .pagination {{ margin-top: 20px; display: flex; justify-content: center; align-items: center; gap: 15px; }}
        .page-btn {{ padding: 8px 16px; background: #fff; border: 1px solid #0088cc; color: #0088cc; border-radius: 4px; text-decoration: none; }}
        .page-btn:disabled {{ border-color: #ccc; color: #ccc; cursor: not-allowed; }}
    </style></head>
    <body>
        <div class="card">
            <h3>1. 批量上传 Session</h3>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="files" multiple>
                <button type="submit" style="background:#27ae60; color:white; border:none;">上传初始化</button>
            </form>
        </div>
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3>2. 账号管理 (总计: {total_count})</h3>
                <div >
                    <button onclick="batchControl('start')" style="background:#27ae60;color:white;border:none;">批量登录</button>
                    <button onclick="batchLogout()" style="background:#95a5a6;color:white;border:none;">批量断开</button>
                    <button onclick="batchChangePW()" style="background:#8e44ad;color:white;border:none;">批量改密(远程)</button>
                    <button onclick="batchChangePWLocal()" style="background:#d35400;color:white;border:none;">批量改密(本地)</button>
                    <button onclick="cleanupDead()" style="background:#c0392b;color:white;border:none;">清理死号</button>
                    <button onclick="location.href='/export_csv'" style="background:#2980b9;color:white;border:none;">导出 CSV</button>
                </div>
            </div>    
            <table>
                <thead><tr>
                    <th><input type="checkbox" onclick="document.querySelectorAll('.sel').forEach(c=>c.checked=this.checked)"></th>
                    <th>序号</th><th>手机号</th><th>2FA</th><th>状态</th><th>操作</th><th>API</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
            
            <div class="pagination">
                <select id="sizeSelect" onchange="changeSize(this.value)" style="padding:5px; border-radius:4px;">
                    {size_options}
                </select>
                <button class="page-btn" {"disabled" if page <= 1 else f"onclick='goPage({page-1})'"}>上一页</button>
                <span>第 {page} / {total_pages} 页</span>
                <button class="page-btn" {"disabled" if page >= total_pages else f"onclick='goPage({page+1})'"}>下一页</button>
            </div>
       
        <script>
            async function control(phone, type) {{
                let url = type === 'logout' ? `/logout?phone=${{phone}}` : `/action?phone=${{phone}}&type=start`;
                await fetch(url); alert('指令已下发'); location.reload();
            }}
            async function deleteConfirm(phone) {{
                if(confirm("确定彻底删除账号 "+phone+" 吗？") && confirm("⚠️ 警告：物理文件将同步删除且无法找回！")) {{
                    let res = await fetch(`/delete_account?phone=${{phone}}`);
                    let data = await res.json(); alert(data.msg); location.reload();
                }}
            }}
            function getSelected() {{ return Array.from(document.querySelectorAll('.sel:checked')).map(i=>i.value); }}
            async function batchControl(type) {{
                let ps = getSelected(); if(!ps.length) return alert('未选择');
                await fetch(`/batch_action?phones=${{ps.join(',')}}&type=${{type}}`); alert('操作成功'); location.reload();
            }}
            async function batchLogout() {{
                let ps = getSelected(); if(!ps.length || !confirm('确认断开？')) return;
                await fetch(`/batch_logout?phones=${{ps.join(',')}}`); location.reload();
            }}
            async function cleanupDead() {{
                if(confirm('清理所有未登录账号？')) {{
                    let res = await fetch('/cleanup_dead_accounts');
                    let data = await res.json(); alert(data.msg); location.reload();
                }}
            }}
            async function batchChangePW() {{
                let ps = getSelected(); if(!ps.length) return alert('未选择');
                let op = prompt('旧密码:', '{DEFAULT_2FA}'), np = prompt('新密码:');
                if(!np) return;
                await fetch(`/batch_update_2fa?phones=${{ps.join(',')}}&old_pw=${{encodeURIComponent(op)}}&new_pw=${{encodeURIComponent(np)}}`);
                alert('任务已提交'); location.reload();
            }}
            async function batchChangePWLocal() {{
                let ps = getSelected();
                if(!ps.length) return alert('请先选择账号');
                let np = prompt('请输入要同步到本地Redis的新二级密码:');
                if(!np) return;

                let res = await fetch(`/batch_update_2fa_local?phones=${{ps.join(',')}}&new_pw=${{encodeURIComponent(np)}}`);
                let data = await res.json();
                alert('本地记录已更新');
                location.reload();
            }}
            async function changePW(phone, isLogin) {{
                if(isLogin !== '1') return alert('请先点登录');
                let op = prompt('旧密码:', '{DEFAULT_2FA}'), np = prompt('新密码:');
                if(!np) return;
                let res = await fetch(`/update_remote_2fa?phone=${{phone}}&old_pw=${{encodeURIComponent(op)}}&new_pw=${{encodeURIComponent(np)}}`);
                let data = await res.json(); alert(data.msg); location.reload();
            }}

            // --- 分页跳转逻辑 ---
            function goPage(p) {{
                let size = document.getElementById('sizeSelect').value;
                location.href = `/admin?page=` + p + `&size=` + size;
            }}
            function changeSize(s) {{
                location.href = `/admin?page=1&size=` + s;
            }}
        </script>
    </body></html>
    """

# --- 3. 功能接口 (全部适配 Cookie 校验) ---

@app.get("/delete_account")
async def delete_account(request: Request, phone: str):
    if not verify_user(request): raise HTTPException(403)
    r.delete(f"active_task:{phone}")
    r.setex(f"logout_task:{phone}", 30, "1")
    await asyncio.sleep(2)
    file_path = os.path.join(SESSION_DIR, f"{phone}.session")
    try:
        if os.path.exists(file_path): os.remove(file_path)
        for k in [f"tg_2fa:{phone}", f"tg_login_status:{phone}", f"tg_code:{phone}"]: r.delete(k)
        return {"status": "ok", "msg": "物理文件已彻底删除"}
    except: return {"status": "error", "msg": "文件锁定中，请稍后再试"}

@app.get("/cleanup_dead_accounts")
async def cleanup_dead(request: Request):
    if not verify_user(request): raise HTTPException(403)
    files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    c = 0
    for f in files:
        p = f.replace('.session', '')
        if r.get(f"tg_login_status:{p}") in [b"0", None]:
            r.delete(f"active_task:{p}")
            try:
                os.remove(os.path.join(SESSION_DIR, f))
                for k in [f"tg_2fa:{p}", f"tg_login_status:{p}", f"tg_code:{p}"]: r.delete(k)
                c += 1
            except: pass
    return {"status": "ok", "msg": f"清理了 {c} 个死号"}

# --- 以下是其他辅助接口 (简化版适配) ---

@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    if not verify_user(request): raise HTTPException(403)
    for file in files:
        if file.filename.endswith('.session'):
            with open(os.path.join(SESSION_DIR, file.filename), "wb") as f: f.write(await file.read())
            p = file.filename.replace('.session', '')
            if not r.exists(f"tg_2fa:{p}"): r.set(f"tg_2fa:{p}", DEFAULT_2FA)
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/export_csv")
async def export(request: Request):
    token = verify_user(request)
    if not token: raise HTTPException(403)
    files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    out = io.StringIO(); out.write('\ufeff手机号,2FA,API链接\n')
    for f in files:
        p = f.replace('.session', '')
        pw = (r.get(f"tg_2fa:{p}") or DEFAULT_2FA.encode()).decode()
        link = f"{BASE_URL}/{token}/{encode_phone(p)}/GetHTML"
        out.write(f"{p},{pw},{link}\n")
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition":"attachment;filename=tg.csv"})

@app.get("/logout")
async def logout(request: Request, phone: str):
    if not verify_user(request): raise HTTPException(403)
    r.delete(f"active_task:{phone}"); r.set(f"tg_login_status:{phone}", "0"); return {"status":"ok"}

@app.get("/action")
async def action(request: Request, phone: str):
    if not verify_user(request): raise HTTPException(403)
    r.setex(f"active_task:{phone}", 300, "run"); return {"status":"ok"}

@app.get("/batch_action")
async def b_action(request: Request, phones: str):
    if not verify_user(request): raise HTTPException(403)
    for p in phones.split(','): r.setex(f"active_task:{p}", 300, "run")
    return {"status":"ok"}

@app.get("/batch_logout")
async def b_logout(request: Request, phones: str):
    if not verify_user(request): raise HTTPException(403)
    for p in phones.split(','): r.delete(f"active_task:{p}"); r.set(f"tg_login_status:{p}", "0")
    return {"status":"ok"}

@app.get("/update_remote_2fa")
async def up_2fa(request: Request, phone: str, old_pw: str, new_pw: str):
    if not verify_user(request): raise HTTPException(403)
    r.setex(f"active_task:{phone}", 300, "run")
    r.setex(f"change_2fa_task:{phone}", 60, f"{old_pw}|{new_pw}")
    for _ in range(15):
        await asyncio.sleep(1); res = r.get(f"change_2fa_res:{phone}")
        if res: r.delete(f"change_2fa_res:{phone}"); return {"status":"ok","msg":res.decode()}
    return {"status":"error","msg":"超时"}

@app.get("/batch_update_2fa")
async def b_2fa(request: Request, phones: str, old_pw: str, new_pw: str):
    if not verify_user(request): raise HTTPException(403)
    for p in phones.split(','):
        r.setex(f"active_task:{p}", 300, "run")
        r.setex(f"change_2fa_task:{p}", 60, f"{old_pw}|{new_pw}")
    return {"status":"ok"}

@app.get("/batch_update_2fa_local")
async def batch_update_2fa_local(request: Request, phones: str, new_pw: str):
    """仅在本地 Redis 中更新 tg_2fa:{phone} 键，不触发任何 session 操作。
    使用 Cookie 中的 admin_token 进行鉴权（与前端行为一致）。"""
    if not verify_user(request):
        raise HTTPException(403)

    phone_list = [p for p in phones.split(',') if p]
    if not phone_list:
        return {"status": "error", "msg": "no phones"}

    results = {}
    for p in phone_list:
        try:
            r.set(f"tg_2fa:{p}", new_pw)
            results[p] = 'ok'
        except Exception as e:
            results[p] = str(e)
    return {"status": "ok", "results": results}

# 唯一保留 Token 在 URL 的地方：验证码查询页（方便外部 API 调用）
@app.get("/{hex_id}/GetHTML", response_class=HTMLResponse)
async def get_html( hex_id: str):
    try:
        p = decode_phone(hex_id)
    except:
        raise HTTPException(404, "Invalid ID")
    r.setex(f"active_task:{p}", 300, "run")
    
    code_raw = r.get(f"tg_code:{p}")
    st = r.get(f"tg_login_status:{p}")
    pw = (r.get(f"tg_2fa:{p}") or DEFAULT_2FA.encode()).decode()
    
    # 保持你原来的颜色逻辑
    color = "#2ecc71" if code_raw else ("#e74c3c" if st == b"0" else "#f39c12")
    msg = code_raw.decode() if code_raw else ("未登录" if st == b"0" else "waitting...")
    
    # --- 动态生成验证码复制按钮 ---
    # 只有当 code_raw 有值时才显示复制验证码按钮
    code_btn = ""
    if code_raw:
        code_btn = f"""
        <button onclick="copyText('{msg}', this)" style='margin-top:10px;padding:8px 16px;background:{color};color:white;border:none;border-radius:5px;cursor:pointer;font-weight:bold;width:100%;'>复制验证码</button>
        """

    return f"""
    <html>
    <head>
        <meta http-equiv='refresh' content='5'>
        <style>
            .copy-notice {{ transition: all 0.3s; }}
        </style>
    </head>
    <body style='text-align:center;padding-top:60px;font-family:sans-serif;background:#f9f9f9;'>
        <div style='display:inline-block;padding:40px;border-radius:20px;box-shadow:0 10px 25px rgba(0,0,0,0.1);border-top:5px solid {color};background:white;'>
            <div style='color:#666;'>账号: {p}</div>
            <h1 style='font-size:60px;color:{color};margin:20px 0;'>{msg}</h1>
            
            <div style='background:#f4f4f4;padding:10px;border-radius:8px;margin-bottom:10px;'>
                二级密码: <b id='pw_val'>{pw}</b>
                <button onclick="copyText('{pw}', this)" style='margin-left:10px;padding:4px 8px;font-size:12px;cursor:pointer;'>复制2FA</button>
            </div>

            {code_btn}
        </div>

       <script>
            function copyText(text, btn) {{
                const oldText = btn.innerText;

                // 优先尝试现代 API (仅 HTTPS/Localhost 支持)
                if (navigator.clipboard && window.isSecureContext) {{
                    navigator.clipboard.writeText(text).then(() => {{
                        showSuccess(btn, oldText);
                    }}).catch(() => {{
                        fallbackCopy(text, btn, oldText);
                    }});
                }} else {{
                    // 强制走兼容模式 (针对 HTTP 环境)
                    fallbackCopy(text, btn, oldText);
                }}
            }}

            function fallbackCopy(text, btn, oldText) {{
                try {{
                    const textArea = document.createElement("textarea");
                    textArea.value = text;
                    textArea.style.position = "fixed";
                    textArea.style.left = "-9999px";
                    textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textArea);
                    if (successful) {{
                        showSuccess(btn, oldText);
                    }} else {{
                        alert('复制失败，请手动选择');
                    }}
                }} catch (err) {{
                    alert('浏览器不支持');
                }}
            }}

            function showSuccess(btn, oldText) {{
                btn.innerText = " 已复制✅";
                btn.style.opacity = "0.7";
                const originalBg = btn.style.background;
                if (originalBg) btn.style.background = "#28a745";

                setTimeout(() => {{
                    btn.innerText = oldText;
                    btn.style.opacity = "1";
                    if (originalBg) btn.style.background = originalBg;
                }}, 1500);
            }}
        </script>
    </body>
    </html>
    """
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)