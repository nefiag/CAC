# 博士特套账Cod

面向博士特及关联账套的现代财务工作台。界面保留财务人员熟悉的业务导航、凭证—审核—记账和账簿联查心智；代码、品牌和数据模型均为博士特套账Cod自有实现。

新 Agent 或维护人员请先阅读 [完整项目说明与 Agent 交接手册](CAC_PROJECT_HANDOFF.md)。应用架构、API 和逐项运行细节见 [应用与运行手册](APPLICATION_OPERATIONS_MANUAL.md)。

面向管理者、使用者与维护者的项目总览及完整文档大纲见 [项目说明与文档大纲](PROJECT_OVERVIEW.md)。

2026-11-16 财务基准重建的完整执行记录、验收结果和私有产物索引见 [工作日记与产物说明](WORK_LOG_AND_ARTIFACTS_2026-11-16.md)。

## 已实现业务闭环

- 多账套及动态会计期间
- 凭证草稿、审核、反审核、记账、反记账和删除
- 凭证键盘录入、科目模糊检索、借贷找平、客户/供应商辅助核算
- 科目余额表 → 明细分类账 → 凭证查询
- 资产负债表、利润表、分类汇总和 Excel 输出
- 银行流水批量导入、分类及智能生单
- 往来辅助余额、合同台账与收付款计划
- 账套凭证/显示/备份策略参数
- 晓会计兼容 Excel 预检、草稿导入、重复跳过及结果报告
- 密码登录、管理员/会计/只读角色、用户启停及账套访问授权

## 启动

```bash
cp .env.example .env
# 在 .env 中设置 POSTGRES_PASSWORD，禁止使用示例或固定密码
docker compose up --build
```

前端默认端口 `3000`，API 默认端口 `8000`，数据库为 `5432`；开发 Compose
仅将这些端口绑定到 `127.0.0.1`。容器启动时先执行 `alembic upgrade head`，
再启动 API 和初始化基础账套数据，应用本身不再隐式修改数据库结构。

手工运行迁移：

```bash
cd backend
DATABASE_URL='postgresql+asyncpg://...' alembic upgrade head
```

## 生产部署

推荐使用腾讯云 Linux 轻量服务器运行 Docker Compose，并通过 Cloudflare Tunnel 暴露 HTTPS，数据库和后端端口不直接开放公网：

```bash
cp .env.production.example .env.production
# 填写随机数据库密码、初始管理员密码和 Cloudflare Tunnel Token
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

现有生产服务器升级必须添加 `-p coxiaoac`，以继续使用既有 `coxiaoac_coxiaoac_pgdata` 数据卷：

```bash
docker compose -p coxiaoac --env-file .env.production -f docker-compose.prod.yml up -d --build
```

当前自托管 Cloudflare Tunnel 的 Public Hostname 为 `cac.bstks.cn`，服务地址为宿主机 `http://127.0.0.1:18810`；若改为 Compose 内置 Tunnel profile，才使用容器服务地址 `http://frontend:80`。首次启动使用 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 创建管理员，首次登录后系统会强制修改初始密码。

生产状态提示（2026-11-17）：域名、HTTPS、前后端品牌已上线；自托管生产库已导入 3,664 张凭证、14,827 条分录及 28 个去重后的财务来源批次。两个法人 2026-10 最新报表已通过“源文件—数据库快照—报表服务”逐行零差异验收；博士特和宇天试算账已分别建立，正式账已锁定且尚无提升请求。详见完整交接手册。

## 验证

```bash
cd frontend && npm install && npm run build
cd ..
python -m pytest -q backend/tests
python -m compileall -q backend/app
```

REA 证据、功能映射和迁移边界见 [迁移分析](docs/xiaokuaiji-3.0-migration.md)。

博士特 2018–2026 历史账簿、昆山宇天银行对账单和两家公司财务报表归纳出的入账、对账、月结及报表规则仅保存于受控的本地财务资料目录，不提交到公开代码仓库。
