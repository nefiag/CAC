# 博士特套账Cod 财务基准重建工作日记与产物说明

> 工作日期：2026-11-16（UTC）  
> 项目：博士特套账Cod（CAC）  
> 状态：已完成，生产基准已上线并通过逐行零差异验收  
> 适用对象：后续开发、财务处理、审计、部署和故障恢复 Agent  
> 安全边界：本文不记录密码、Token、数据库连接串、服务器公网地址或真实交易明细。

## 1. 本轮目标与最终结论

本轮目标是以指定财务报表目录为唯一文件来源，完成源文件清点、逻辑去重、基准重建试算、最新一期报表完全对齐、生产导入、代码同步和前后端部署。

最终结论：

- 指定目录内共有 35 个 Excel 工作簿；未发现银行对账单 PDF。
- 按“法人＋期间＋文档类型”去重后采用 28 个权威工作簿，排除 7 个逻辑副本。
- 生产库已建立 431 个科目、3,664 张凭证和 14,827 条分录。
- 3,664 张凭证全部借贷平衡。
- 两个法人最新期间均为 `2026-10`。
- 两个法人各自的科目余额表、利润表和资产负债表，共 6 份、408 行，均已完成“源 Excel → 数据库快照 → 报表服务输出”三层逐行比较。
- 文件哈希、行数、文本字段和金额字段全部一致；金额按 `0.01` 元精度比较。
- 最终结果为 `gate_passed=true`、`total_mismatches=0`。
- GitHub、Windows 工作副本和自托管生产环境均已同步。

## 2. 输入范围与源文件证据

### 2.1 原始来源

Windows 受控源目录：

```text
D:\Backup Z8NB\博士特公司\银行财务\博士特财务报表
```

源目录只读清点结果：

| 项目 | 结果 |
|---|---:|
| Excel 文件 | 35 |
| PDF 对账单 | 0 |
| 文件总大小 | 3,339,732 字节 |
| 法人主体 | 2 |
| 最新会计期间 | 2026-10 |

两个法人：

1. 博士特电子科技（昆山）有限公司；
2. 昆山宇天新能源科技有限公司。

### 2.2 源文件归档

Windows 只读归档：

```text
D:\WorkSpace\Codex\cac-financial-source-20261116.zip
```

归档属性：

```text
大小：3,028,881 字节
SHA-256：e889799e67806762f7d7f94fc26582a5920884f55294e75c18cdd4d1cdad6a5e
```

Linux 受控副本：

```text
/home/nefia/Coxiaoac/private-backups/source-20261116/
```

`private-backups/` 已被 Git 忽略，原始财务资料不得提交到公开仓库。

### 2.3 生产导入包

生产传输包：

```text
/tmp/cac-baseline-input-20261116.tar.gz
```

SHA-256：

```text
9f35c01464cf3ca957ecdc522f83da15f2c68d60c91ac3594f8c106d622a3fef
```

传输包包含 35 个源工作簿，以及受控分析目录中的 `vouchers.json` 和 `statement-summaries.csv`。真实财务内容未进入 Git。

## 3. 工作日记

### 3.1 源目录清点与完整性固定

1. 通过已授权 SSH 只读访问 Windows 源目录。
2. 枚举全部文件、大小、修改时间和 SHA-256。
3. 确认指定目录包含 35 个 Excel、0 个 PDF。
4. 创建 ZIP，并在传输前后核对 SHA-256。
5. 在 Linux 私有目录解压，保持原文件内容不变。

结果：传输前后归档哈希一致，源文件证据链建立完成。

### 3.2 逻辑去重与导入预演

使用：

```text
backend/scripts/rebuild_financial_baseline.py
```

工作簿业务键：

```text
account_set_id + period + document_type
```

同一业务键存在多个文件时，优先选择正常命名的原件，再按相对路径长度和稳定排序选择权威文件。副本即使二进制哈希不同，也不会重复入账。

预演结果：

| 项目 | 结果 |
|---|---:|
| 源 Excel | 35 |
| 选中工作簿 | 28 |
| 排除逻辑副本 | 7 |
| 历史凭证 | 3,664 |
| 末级科目分录 | 14,827 |
| 凭证涉及科目 | 242 |
| 借贷不平凭证 | 0 |

预演只读取文件和数据库，不写入生产数据。

### 3.3 增加完全对齐发布门禁

新增程序：

```text
backend/scripts/verify_latest_financial_alignment.py
```

门禁执行以下检查：

1. 使用相同确定性规则选取权威工作簿；
2. 为每个法人选择每类报表的最新期间；
3. 核对活动导入批次的源 SHA-256；
4. 逐行比较源工作簿与数据库快照；
5. 逐行比较源工作簿与报表服务输出；
6. 文本字段去除首尾空白后精确比较；
7. 金额统一量化为两位小数后精确比较；
8. 检查报表服务确实使用权威来源快照；
9. 任一差异都令程序以非零状态退出。

新增回归测试：

```text
backend/tests/test_financial_alignment.py
```

它验证金额表示等价性、字段差异、缺行和行数不一致均能被正确识别。

### 3.4 隔离试算验收

在已有受控基准数据库上先运行完全对齐门禁，未直接操作生产库。

试算覆盖：

| 法人 | 报表 | 期间 | 行数 | 差异 |
|---|---|---:|---:|---:|
| 博士特电子科技（昆山）有限公司 | 科目余额表 | 2026-10 | 180 | 0 |
| 博士特电子科技（昆山）有限公司 | 利润表 | 2026-10 | 32 | 0 |
| 博士特电子科技（昆山）有限公司 | 资产负债表 | 2026-10 | 32 | 0 |
| 昆山宇天新能源科技有限公司 | 科目余额表 | 2026-10 | 100 | 0 |
| 昆山宇天新能源科技有限公司 | 利润表 | 2026-10 | 32 | 0 |
| 昆山宇天新能源科技有限公司 | 资产负债表 | 2026-10 | 32 | 0 |
| **合计** | **6 份报表** |  | **408** | **0** |

只有该阶段通过后才进入生产迁移。

### 3.5 生产备份

正式写入前完成 PostgreSQL 全量逻辑备份，备份保存在生产服务器私有目录：

```text
/home/ubuntu/CAC-private/baseline-20261116/pre-import.sql.gz
```

SHA-256：

```text
537d3dab4954d30a0ee308c05dacdd11c6630845ecd466ad735bbb76c900c6f6
```

迁移前业务库计数：

```text
凭证 0；分录 0；财务来源批次 0；财务来源行 0
```

备份和生产输入包权限受服务器账户控制，不对公网开放。

### 3.6 生产基准导入

执行顺序：

1. 在生产容器环境再次运行只读预演；
2. 确认 28 个权威工作簿、7 个副本、3,664 张凭证和 14,827 条分录；
3. 使用 `--apply` 在单个数据库事务中清空财务业务域；
4. 保留用户、Session、用户—账套授权和系统配置；
5. 导入来源快照、科目、余额、报表、历史凭证和分录；
6. 在事务提交前执行数据库级借贷平衡检查；
7. 任一异常会使整个事务回滚。

导入后生产计数：

| 数据表/对象 | 数量 |
|---|---:|
| `chart_of_accounts` | 431 |
| `vouchers` | 3,664 |
| `voucher_entries` | 14,827 |
| `financial_import_batches` | 28 |
| `financial_source_rows` | 69,222 |
| `financial_balance_snapshots` | 280 |
| `financial_report_snapshot_rows` | 256 |
| `bank_accounts` | 1 |
| `bank_statements` | 0 |

`bank_statements=0` 是预期结果，因为本轮指定源目录没有 PDF 或其他银行对账单文件。不得伪造银行流水补齐该计数。

### 3.7 生产逐行验收

生产导入后、部署后分别运行了一次只读门禁。最终部署后结果：

```json
{
  "status": "PASS",
  "total_mismatches": 0,
  "gate_passed": true,
  "total_source_rows": 408
}
```

完整私有证据：

```text
/home/ubuntu/CAC-private/baseline-20261116/evidence/latest-alignment.json
/home/ubuntu/CAC-private/baseline-20261116/evidence/post-deploy-alignment.json
```

### 3.8 测试、同步与部署

测试结果：

```text
后端：12 passed
后端 compileall：通过
前端 TypeScript + Vite 生产构建：通过
```

代码提交：

| Commit | 内容 |
|---|---|
| `ce9147c` | 增加完全对齐门禁、回归测试并更新基准文档 |
| `d5a824a` | 更正验收总行数为 408 |

同步目标：

```text
GitHub origin:   nefiag/CAC main
Windows:         D:\WorkSpace\Codex\CAC
生产项目目录:    /home/ubuntu/Coxiaoac
```

> 后续政策更新：本轮执行时曾同步 `nefiag/GeAccounting`，但用户随后明确要求停止。自该要求起，CAC 只同步 `nefiag/CAC`；不得根据本工作日记的历史记录恢复对 GeAccounting 的推送。

部署使用现有生产 Compose 项目标识 `coxiaoac`，以继续使用正式数据卷：

```bash
sudo docker compose -p coxiaoac \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  up -d --build backend frontend
```

前端随后执行强制重建，最终检查结果：

```text
数据库：healthy
后端：running
前端：running
本机前端 HTTP：200
公网 HTTPS：200
页面标题：博士特套账Cod
后端标题：博士特套账Cod API
```

## 4. 产物清单

### 4.1 已提交代码仓库

| 产物 | 用途 |
|---|---|
| `backend/scripts/verify_latest_financial_alignment.py` | 最新报表源文件、数据库、服务输出三层对齐门禁 |
| `backend/tests/test_financial_alignment.py` | 门禁比较逻辑回归测试 |
| `APPLICATION_OPERATIONS_MANUAL.md` | 架构、财务规则、运行、部署、恢复主手册 |
| `WORK_HANDOFF.md` | 后续 Agent 快速接手摘要 |
| `项目说明.md` | 项目功能与生产状态说明 |
| `README.md` | 项目入口说明 |
| `WORK_LOG_AND_ARTIFACTS_2026-11-16.md` | 本轮工作日记与产物索引 |

### 4.2 Linux 私有产物

```text
/home/nefia/Coxiaoac/private-backups/source-20261116/
  cac-financial-source-20261116.zip
  extracted/
  baseline-dry-run-current.json
  render-latest-alignment.json
```

这些文件被 Git 忽略，不得强制加入版本控制。

### 4.3 生产服务器私有产物

```text
/home/ubuntu/CAC-private/baseline-20261116/
  cac-baseline-input-20261116.tar.gz
  pre-import.sql.gz
  input/
  evidence/
    verify_latest_financial_alignment.py
    latest-alignment.json
    post-deploy-alignment.json
```

### 4.4 Windows 产物

```text
D:\WorkSpace\Codex\cac-financial-source-20261116.zip
D:\WorkSpace\Codex\CAC
```

Windows CAC 工作副本最终提交为 `d5a824a`。

## 5. 日常复验方式

### 5.1 代码测试

```bash
cd /home/nefia/Coxiaoac
.venv/bin/python -m pytest -q backend/tests
.venv/bin/python -m compileall -q backend/app backend/scripts
cd frontend && npm run build
```

### 5.2 最新报表对齐

在已设置正确 `DATABASE_URL` 的受控环境中：

```bash
python backend/scripts/verify_latest_financial_alignment.py \
  --source /受控/财务报表目录 \
  --report private-backups/latest-financial-alignment.json
```

验收条件必须同时满足：

```text
进程退出码 = 0
status = PASS
gate_passed = true
total_mismatches = 0
```

### 5.3 生产健康检查

```bash
cd /home/ubuntu/Coxiaoac
sudo docker compose -p coxiaoac \
  --env-file .env.production \
  -f docker-compose.prod.yml ps
```

不要省略 `-p coxiaoac`，否则可能创建新的空数据卷。

## 6. 恢复说明

如需恢复本轮导入前状态：

1. 立即停止业务写入；
2. 再备份一次故障现场数据库；
3. 核对恢复目标、备份 SHA-256 和 PostgreSQL 实例身份；
4. 验证备份可以正常解压和读取；
5. 仅在明确授权后恢复 `pre-import.sql.gz`；
6. 恢复后检查用户、权限、账套、凭证、分录和来源快照计数；
7. 重新运行健康检查和对齐门禁。

恢复属于破坏性操作。不得仅凭文件名直接覆盖生产库，也不得删除正式 Docker 数据卷。

## 7. 后续对账单处理规则

本轮已经建立历史财务基准。以后上传对账单必须采用追加流程：

```text
原文件保存与 SHA-256
  → 内容识别银行、法人和账号
  → 解析及字段标准化
  → 文件级笔数、收支合计和余额勾稽
  → 稳定指纹去重
  → 确定性规则分类
  → AI 建议（可选，不作为事实）
  → 例外人工确认
  → 草稿凭证
  → 审核
  → 记账
  → 余额、账簿和报表复核
```

后续处理中不得：

- 为普通新增对账单运行 `rebuild_financial_baseline.py --apply`；
- 仅凭文件名判断银行或法人；
- 把收付款直接等同于收入费用；
- 用 `0` 代替缺失余额；
- 将解析失败报告为“成功导入 0 条”；
- 让 AI 直接覆盖原始银行字段或绕过人工审核记账；
- 把真实对账单、数据库备份或敏感映射提交到公开 GitHub。

## 8. 后续 Agent 接手顺序

后续 Agent 应依次阅读：

1. `WORK_HANDOFF.md`；
2. 本文；
3. `APPLICATION_OPERATIONS_MANUAL.md`；
4. `README.md`；
5. 与当前任务直接相关的代码和测试。

开始新增对账单处理前，应先确认：

- 当前 Git 提交不早于 `d5a824a`；
- 生产凭证数为 3,664、分录数为 14,827；
- 基准门禁仍为零差异；
- 新文件已先保存原件并计算 SHA-256；
- 新数据属于哪个法人和银行账户；
- 当前操作是“追加处理”，不是“整体重建”。
