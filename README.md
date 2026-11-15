# Coxiaoac

面向晓会计个人版 3.0 操作员迁移的现代财务工作台。界面沿用其顶部业务域、业务导航、凭证—审核—记账、账簿联查等操作心智；代码、品牌和数据模型均为 Coxiaoac 自有实现。

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

## 启动

```bash
docker compose up --build
```

前端默认端口 `3000`，API 默认端口 `8000`。首次启动由后端自动创建数据库表和基础账套数据。

## 生产部署

推荐使用腾讯云 Linux 轻量服务器运行 Docker Compose，并通过 Cloudflare Tunnel 暴露 HTTPS，数据库和后端端口不直接开放公网：

```bash
cp .env.production.example .env.production
# 填写随机数据库密码和 Cloudflare Tunnel Token
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Cloudflare Tunnel 的 Public Hostname 设置为 `coxiaoa.bstks.cn`，服务地址设置为 `http://frontend:80`。

## 验证

```bash
cd frontend && npm install && npm run build
cd ..
python -m pytest -q backend/tests
python -m compileall -q backend/app
```

REA 证据、功能映射和迁移边界见 [迁移分析](docs/xiaokuaiji-3.0-migration.md)。
