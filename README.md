# pairwise-combat-status

游戏系统bug修复项目。

## 结构
- combat/status.py: 核心模块（含bug）
- tests/test_status.py: 验收测试（红态，修复后应全绿）

## 运行测试
```bash
python -m pytest tests/test_status.py -q
```

## 要求
- 只修改核心模块，不要改测试
- 纯Python标准库
