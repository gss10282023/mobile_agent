# infra/db/__init__.py
# 保持包轻量：不要在此处 from .session import Base 或 from .engine import engine
# 避免导入链副作用导致的 ModuleNotFoundError / 循环依赖
