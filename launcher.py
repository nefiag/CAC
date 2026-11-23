import sys
import os
import uvicorn

from database_url import database_url_for_launcher

# 1. 确定运行目录与打包解压目录
if getattr(sys, 'frozen', False):
    app_dir = os.path.dirname(sys.executable)
    bundle_dir = sys._MEIPASS
else:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    bundle_dir = app_dir

# 2. 在导入任何业务代码前，强制加载外部同级目录下的 .env 文件
env_path = os.path.join(app_dir, ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# 3. 未配置数据库时才使用同级 SQLite；显式 PostgreSQL 配置必须原样保留。
os.environ["DATABASE_URL"] = database_url_for_launcher(app_dir, os.environ.get("DATABASE_URL"))

# 4. 加入内部打包的 backend 搜索路径
backend_path = os.path.join(bundle_dir, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 5. 在顶层直接导入 app，让 PyInstaller 自动静态追踪所有子模块（如 pdfplumber、openai 等）
from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
