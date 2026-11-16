# 博士特套账Cod

面向博士特及关联账套的现代财务工作台。界面保留财务人员熟悉的业务导航、凭证—审核—记账和账簿联查心智；代码、品牌和数据模型均为博士特套账Cod自有实现。

应用架构、财务基准、对账单处理、部署、恢复和 Agent 接手流程见 [应用与运行手册](APPLICATION_OPERATIONS_MANUAL.md)。

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
docker compose up --build
```

前端默认端口 `3000`，API 默认端口 `8000`。首次启动由后端自动创建数据库表和基础账套数据。

## 生产部署

推荐使用腾讯云 Linux 轻量服务器运行 Docker Compose，并通过 Cloudflare Tunnel 暴露 HTTPS，数据库和后端端口不直接开放公网：

```bash
cp .env.production.example .env.production
# 填写随机数据库密码、初始管理员密码和 Cloudflare Tunnel Token
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Cloudflare Tunnel 的 Public Hostname 设置为 `cac.bstks.cn`，服务地址设置为 `http://frontend:80`。首次启动使用 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 创建管理员，首次登录后系统会强制修改初始密码。

## 验证

```bash
cd frontend && npm install && npm run build
cd ..
python -m pytest -q backend/tests
python -m compileall -q backend/app
```

REA 证据、功能映射和迁移边界见 [迁移分析](docs/xiaokuaiji-3.0-migration.md)。

博士特 2018–2026 历史账簿、昆山宇天银行对账单和两家公司财务报表归纳出的入账、对账、月结及报表规则仅保存于受控的本地财务资料目录，不提交到公开代码仓库。
