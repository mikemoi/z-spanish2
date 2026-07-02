"""集中配置。所有可变项走环境变量，给出方便本地运行的默认值。"""
import os
from pathlib import Path

# PIN 由后端验证，绝不写进前端。部署时改环境变量 Z_SPANISH_PIN。
PIN = os.environ.get("Z_SPANISH_PIN", "1234")

# 数据目录：本地默认放在 backend/data，Docker 里挂载到 /data 做持久化 + 备份。
_default_data = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("Z_SPANISH_DATA", str(_default_data)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "z-spanish.db"

# 种子词条：读 seed 目录下所有 *.json 合并（每个场景一个文件，可单独审核）。
# 优先用 data/seed（部署时可挂载自定义），否则用仓库自带的 backend/seed。
DATA_SEED_DIR = DATA_DIR / "seed"
REPO_SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# 前端静态文件目录
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# 间隔复习节奏：idx 0..7 -> 今天/第2/第4/第7/第14/第30/第60/第90 天
# GAP_TO_IDX[i] = 从上一次复习到到达该 idx 的天数间隔（idx0 = 新词当天到期）
GAP_TO_IDX = [0, 1, 2, 3, 7, 16, 30, 30]
MAX_IDX = len(GAP_TO_IDX) - 1  # 7

# 每日剂量
DAILY_TOTAL = 20        # 每天目标题量
NEW_CAP = 5             # 新内容硬上限（状态再好也不放宽）
OLD_BLOCK_NEW = 20      # 旧内容 >= 此值 -> 今天不加新内容
REINFORCE_SOFT_CAP = 15 # 需要加强池 > 此值 -> 当日优先清空，不加新内容
