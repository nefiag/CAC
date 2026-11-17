# 博士特套账Cod 工作交接记录

## 2026-11-17：正式/试算双层账套与强制回滚点

- 博士特、宇天分别新增固定试算账套设计；正式 ID 保持 `...001 / ...002`，试算 ID 为 `...101 / ...102`。
- 新增 `account_set_environments`、`ledger_backup_records`、`ledger_change_batches`、`ledger_promotion_requests`。
- 正式账环境为 `FORMAL / PROMOTION_ONLY`；凭证、对账单、财务报表、合同等网页写入口只接受 `TRIAL / TRIAL_WRITABLE`。
- 每次账务写入前必须实际 `pg_dump`、校验目录并记录 SHA-256；失败即禁止写入。
- `scripts/create_trial_ledgers.sh` 先备份再原子克隆两套正式基准；已有试算账时拒绝覆盖。
- `scripts/restore_ledger_backup.sh` 恢复前再次备份当前状态，并要求准确确认短语。
- 正式提升入口尚未开放，这是审批控制而非缺陷；必须等用户针对具体已验证批次再次明确确认。
- 本轮后端测试 `12 passed`，前端 TypeScript/Vite 生产构建通过。

### 生产落地结果（2026-11-17 UTC）

- 已部署到 `cac.bstks.cn` 当前自托管生产环境，正式基准在变更前仍为 2 个账套、3,664 张凭证、14,827 条分录、0 张不平衡凭证。
- 创建前完整备份：`/home/ubuntu/Coxiaoac/backups/ledger/pre-create-trials-20261117T072040Z.dump`，SHA-256 `f9d4fc96b354158932125e4795c574ab6d34990f74b888f55e15ccc445794574`，4,096,405 字节，已通过 `pg_restore --list`。
- 已实际创建博士特试算账套 `...0101` 和宇天试算账套 `...0102`；两个 `BASELINE_CLONE` 批次状态均为 `VALIDATED`，提升请求为 0。
- 博士特正式/试算均为 331 科目、160 条余额、23 个来源批次、68,977 条源表行、3,664 张凭证、14,827 条分录；借贷总额均为 `777,523,851.14`。
- 宇天正式/试算均为 100 科目、83 条余额、5 个来源批次、245 条源表行；宇天当前权威基准没有凭证，试算克隆也保持 0，不虚构凭证。
- 全库克隆后不平衡凭证为 0；正式账行数没有发生变化。
- 生产自动备份链路已用 `BACKUP_PIPELINE_SELF_TEST` 实测，成功生成 8,119,392 字节备份并登记 SHA-256；备份文件权限为 `600`。
- 生产正式账继续保持 `FORMAL / PROMOTION_ONLY`；没有用户针对具体批次再次明确确认前，不得创建或执行提升。

> 状态日期：2026-11-16（UTC）  
> 用途：供后续 Agent 快速恢复上下文、核验现状并继续工作。  
> 安全要求：本文不得记录密码、Cookie、OAuth Token、数据库连接串、API Key、原始财务文件或个人信息。

## 1. 当前结论

- 应用正式品牌已经改为“博士特套账Cod”。
- 正式入口 `https://cac.bstks.cn` 已启用，DNS、HTTPS、Cloudflare Tunnel 和页面访问均已验证。
- 生产页面标题为“博士特套账Cod”；自托管后端应用标题为“博士特套账Cod API 1.0.0”。
- 旧域名 `coxiaoac.bstks.cn` 暂时保留，避免切换期间中断。
- 当前自托管生产 PostgreSQL 已迁入权威基准：431 个科目、3,664 张凭证、14,827 条分录、28 个来源批次、69,222 行源表数据。
- 全部凭证借贷平衡；两个法人 2026-10 的 6 份最新报表共 408 行，在源文件、数据库快照、报表服务三层逐行核验为 0 差异。
- 导入前数据库备份、源包哈希和验收 JSON 保存在服务器私有目录，不提交公开 Git 仓库。

## 2. 代码与仓库状态

主工作目录：

```text
/home/nefia/Coxiaoac
```

Windows 协作目录：

```text
D:\WorkSpace\Codex\CAC
```

Git 远端：

```text
origin https://github.com/nefiag/CAC.git
```

同步政策：CAC 只允许推送到 `nefiag/CAC`。不得再向 `nefiag/GeAccounting` 同步代码、文档或其他项目产物；本地和 Windows 工作副本中的旧 `upstream` 远端已移除。

`/home/nefia/Coxiaoac` 和 `D:\WorkSpace\Codex\CAC` 是同一项目的 Linux/Windows 工作副本。GitHub 主仓库已从 `nefiag/Coxiaoac` 更名为 `nefiag/CAC`；GitHub 会为旧地址提供重定向，但所有新配置必须使用新地址。本地与生产目录仍保留 `Coxiaoac` 兼容名，不能仅为名称一致而直接移动生产目录。

关键提交：

| 提交 | 内容 |
|---|---|
| `bd2fa99` | 应用品牌改为“博士特套账Cod” |
| `cac817d` | 记录 Render 服务显示名调整 |
| `c8767e5` | 更新生产拓扑、数据基准差异和部署兼容说明 |

品牌改名保留了以下兼容性技术标识，避免破坏数据和部署：历史仓库名、服务器目录 `/home/ubuntu/Coxiaoac`、数据库名、数据卷名及 Render 旧 URL slug。

## 3. Cloudflare 与域名工作记录

1. 在 Windows `100.88.50.72` 上安装临时 Wrangler 并完成 OAuth 设备授权。
2. OAuth 凭据由 Wrangler 保存在当前 Windows 用户配置目录；不得复制到文档或聊天。
3. 查询到健康的生产 Tunnel：`boshite-park`。
4. 在 Tunnel 远程配置中加入：

   ```text
   cac.bstks.cn → http://127.0.0.1:18810
   ```

5. Cloudflare DNS 添加了已代理 CNAME，目标为该 Tunnel 的 `cfargotunnel.com` 地址。
6. Tunnel 配置变更前的备份位于：

   ```text
   D:\WorkSpace\Codex\cloudflare-tunnel-config-backup-20261117-001847.json
   ```

7. OAuth 临时生成的 `node_modules`、`package.json` 和 `package-lock.json` 已从 `D:\WorkSpace\Codex` 清理；OAuth 凭据和 Tunnel 备份保留。

## 4. 生产部署工作记录

生产目录：

```text
/home/ubuntu/Coxiaoac
```

生产链路：

```text
cac.bstks.cn
  → Cloudflare Tunnel boshite-park
  → 127.0.0.1:18810
  → Nginx 前端
  → 同源 /api/*
  → FastAPI backend:8000
  → PostgreSQL 15 内部网络
```

部署前完成数据库备份：

```text
/home/ubuntu/Coxiaoac-backups/before-brand-deploy-20261116T162549Z.dump
SHA-256 511c0e24495409e83ff0347eebb8eb2b22f5654d5b59c134392f9a40a20e0998
```

该备份对应当时的生产库：2 个账套、0 张凭证、0 条分录，不包含受控权威历史基准。

生产数据卷是：

```text
coxiaoac_coxiaoac_pgdata
```

由于 Compose 文件的品牌项目名已经改变，现有生产升级必须显式使用旧项目标识：

```bash
cd /home/ubuntu/Coxiaoac
sudo docker compose -p coxiaoac \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  up -d --build backend frontend
```

遗漏 `-p coxiaoac` 会创建新的空数据卷。取消兼容参数前必须完成卷迁移、备份恢复演练及逐表核验。

## 5. 已执行验证

- 前端生产构建成功。
- 后端容器和前端容器成功原地重建。
- PostgreSQL 容器保持运行并继续使用原数据卷。
- `https://cac.bstks.cn/` 返回 HTTP 200。
- 公网页面标题核验为“博士特套账Cod”。
- 后端进程内应用标题核验为“博士特套账Cod API 1.0.0”。
- DNS 返回 Cloudflare 代理地址。
- 品牌部署当时的生产行数为 2 个账套、0 张凭证、0 条分录；随后已按第 7 节完成权威基准迁移，当前以 3,664 张凭证、14,827 条分录为准。

## 6. Render 兼容服务

Render 服务显示名已经改为 `boshite-ledger-cod-api`，服务 ID 和旧 URL slug 为兼容性标识。当前 `cac.bstks.cn` 的主链路使用自托管同源后端，不能仅凭 Render `live` 状态判断自托管生产是否发布成功。

## 7. 已完成基准迁移与下一优先级

### 7.1 权威基准迁入生产（已完成）

迁移采用 `backend/scripts/rebuild_financial_baseline.py` 单事务执行，仅替换财务业务域并保留认证权限域。生产结果为 431/3,664/14,827/28/69,222（科目/凭证/分录/来源批次/来源行），最新报表门禁 `gate_passed=true`、`total_mismatches=0`。

不得为普通新增对账单再次运行 `--apply` 基准重建；只有明确要求整体重建、完成新备份及隔离预演后才能使用。

### 7.2 后续对账单处理

严格按 `APPLICATION_OPERATIONS_MANUAL.md` 的文件哈希、解析、文件级勾稽、稳定去重、分类、草稿制证、人工审核和记账流程追加数据。普通新增对账单不得调用基准重建脚本。

## 8. 下次接手的快速检查

```bash
cd /home/nefia/Coxiaoac
git status --short --branch
git log -5 --oneline
git remote -v
```

生产只读检查：

```bash
cd /home/ubuntu/Coxiaoac
sudo docker compose -p coxiaoac --env-file .env.production -f docker-compose.prod.yml ps
curl -I http://127.0.0.1:18810/
curl -I https://cac.bstks.cn/
```

继续工作前应依次阅读：

1. `WORK_HANDOFF.md`；
2. `APPLICATION_OPERATIONS_MANUAL.md`；
3. `项目说明.md`；
4. `README.md`；
5. 与当前任务直接相关的服务、脚本和测试。

## 9. 完成定义

本轮品牌与域名工作在以下条件下完成：

- 新品牌代码和文档进入两个 GitHub 仓库；
- Windows `D:\WorkSpace\Codex\CAC` 拥有可继续开发的完整 Git 工作副本；
- `cac.bstks.cn` 可通过 HTTPS 打开；
- 前后端品牌正确；
- Tunnel 和生产数据库均有变更前备份；
- 文档记录生产基准已迁入及零差异验收门禁，后续 Agent 以此为追加处理起点。
