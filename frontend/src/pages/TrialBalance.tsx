import React, { useEffect, useState } from 'react';
import { Card, Table, Button, Space, Tag, Upload, message, Modal } from 'antd';
import { DownloadOutlined, UploadOutlined, SyncOutlined } from '@ant-design/icons';
import { api } from '../api';

export const TrialBalance: React.FC<{
  accountSetId: string;
  period: string;
  refreshKey: number;
  onRefreshBootstrap: () => void;
  onOpenVoucher?: (voucherId: string) => void;
}> = ({ accountSetId, period, refreshKey, onRefreshBootstrap, onOpenVoucher }) => {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [ledger, setLedger] = useState<any>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await api.get('/reports/trial-balance', { params: { account_set_id: accountSetId, period } });
      setData(res.data);
    } finally {
      setLoading(false);
    }
  };

  const openLedger = async (row: any) => {
    setLedgerLoading(true);
    setLedger({ account_code: row.code, account_name: row.name, rows: [] });
    try {
      const res = await api.get('/reports/subsidiary-ledger', {
        params: { account_set_id: accountSetId, account_code: row.code, start_period: period, end_period: period },
      });
      setLedger(res.data);
    } catch { message.error('明细分类账加载失败'); }
    finally { setLedgerLoading(false); }
  };

  useEffect(() => {
    loadData();
  }, [accountSetId, period, refreshKey]);

  const handleImportXkj = async (opt: any) => {
    const fd = new FormData();
    fd.append('file', opt.file);
    const inspection = await api.post('/migration/inspect-xiaokuaiji', fd);
    if (!inspection.data.valid) {
      Modal.error({ title: '迁移预检未通过', width: 620, content: <div>{inspection.data.errors.map((e: string) => <p key={e}>• {e}</p>)}</div> });
      return;
    }
    const ok = await new Promise<boolean>((resolve) => Modal.confirm({
      title: '晓会计数据迁移预检通过',
      content: <div><p>科目：{inspection.data.account_rows} 行</p><p>凭证：{inspection.data.voucher_count} 张 / {inspection.data.voucher_rows} 条分录</p><p>导入凭证将保存为草稿，复核后再审核记账。</p></div>,
      onOk: () => resolve(true), onCancel: () => resolve(false),
    }));
    if (!ok) return;
    const importFd = new FormData(); importFd.append('account_set_id', accountSetId); importFd.append('file', opt.file);
    const res = await api.post('/migration/import-xiaokuaiji', importFd);
    message.success(`迁移完成：新增科目 ${res.data.imported_accounts} 个，导入凭证 ${res.data.imported_vouchers} 张，跳过重复 ${res.data.skipped_vouchers} 张`);
    loadData();
    onRefreshBootstrap();
  };

  const handleImportFinancialReports = async (opt: any) => {
    const files: File[] = opt.fileList?.map((x: any) => x.originFileObj || x).filter(Boolean) || [opt.file];
    const fd = new FormData(); files.forEach((file) => fd.append('files', file));
    try {
      const inspection = await api.post('/financial-imports/inspect', fd);
      if (!inspection.data.valid) {
        const errors = inspection.data.files.flatMap((f: any) => (f.errors || []).map((e: string) => `${f.filename}：${e}`));
        Modal.error({ title: '财务报表预检未通过', width: 720, content: <div>{errors.map((e: string) => <p key={e}>• {e}</p>)}</div> });
        opt.onError?.(new Error('预检未通过')); return;
      }
      const confirmed = await new Promise<boolean>((resolve) => Modal.confirm({
        title: '导入已验证财务报表', width: 720,
        content: <div>{inspection.data.files.map((f: any) => <p key={f.sha256}>• {f.company_name} · {f.period} · {f.document_type} · {f.row_count} 行</p>)}<p>系统将保留源文件哈希和逐行快照；同一主体、期间、报表类型以最新验证批次为当前版本。</p></div>,
        onOk: () => resolve(true), onCancel: () => resolve(false),
      }));
      if (!confirmed) { opt.onError?.(new Error('已取消')); return; }
      const importFd = new FormData(); importFd.append('account_set_id', accountSetId); files.forEach((file) => importFd.append('files', file));
      const result = await api.post('/financial-imports/import', importFd);
      message.success(`导入完成：新增 ${result.data.imported}，重复 ${result.data.duplicates}，失败 ${result.data.failed}`);
      opt.onSuccess?.(result.data); loadData(); onRefreshBootstrap();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '财务报表导入失败'); opt.onError?.(error);
    }
  };

  return (
    <Card
      title={`科目余额表（会计期间：${period}）`}
      extra={
        <Space>
          <Upload customRequest={handleImportFinancialReports} showUploadList={false} accept=".xlsx" multiple>
            <Button icon={<UploadOutlined />}>导入财务报表（原表对齐）</Button>
          </Upload>
          <Upload customRequest={handleImportXkj} showUploadList={false} accept=".xlsx">
            <Button icon={<UploadOutlined />}>导入晓会计 Excel 模板</Button>
          </Upload>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            href={`/api/v1/migration/export-xiaokuaiji?account_set_id=${accountSetId}&period=${period}`}
          >
            导出晓会计兼容格式 (.xlsx)
          </Button>
          <Button icon={<SyncOutlined />} onClick={loadData} />
        </Space>
      }
    >
      <Table
        rowKey="code"
        loading={loading}
        dataSource={data}
        pagination={false}
        bordered
        size="small"
        columns={[
          { title: '科目编码', dataIndex: 'code', width: 110 },
          {
            title: '科目名称',
            dataIndex: 'name',
            render: (name, r) => <a style={{ paddingLeft: (r.level - 1) * 16 }} onClick={() => openLedger(r)}>{name}</a>,
          },
          { title: '类别', dataIndex: 'category', width: 80, render: (c) => <Tag>{c}</Tag> },
          { title: '期初借方', dataIndex: 'opening_debit', align: 'right', render: (v) => v.toFixed(2) },
          { title: '期初贷方', dataIndex: 'opening_credit', align: 'right', render: (v) => v.toFixed(2) },
          { title: '本期借方发生', dataIndex: 'period_debit', align: 'right', render: (v) => v.toFixed(2) },
          { title: '本期贷方发生', dataIndex: 'period_credit', align: 'right', render: (v) => v.toFixed(2) },
          { title: '本年累计借方', dataIndex: 'ytd_debit', align: 'right', render: (v) => v === undefined ? '' : v.toFixed(2) },
          { title: '本年累计贷方', dataIndex: 'ytd_credit', align: 'right', render: (v) => v === undefined ? '' : v.toFixed(2) },
          {
            title: '期末借方余额',
            dataIndex: 'closing_debit',
            align: 'right',
            render: (v) => <strong>{v.toFixed(2)}</strong>,
          },
          {
            title: '期末贷方余额',
            dataIndex: 'closing_credit',
            align: 'right',
            render: (v) => <strong>{v.toFixed(2)}</strong>,
          },
        ]}
      />
      <Modal
        open={!!ledger}
        width={1050}
        title={`明细分类账 · ${ledger?.account_code || ''} ${ledger?.account_name || ''}`}
        onCancel={() => setLedger(null)}
        footer={<Button onClick={() => setLedger(null)}>关闭</Button>}
      >
        <div style={{ marginBottom: 8, color: '#6b7b84' }}>查询范围：{period}　包含草稿、已审核和已记账凭证；余额表金额仅统计已记账凭证。</div>
        <Table
          rowKey={(_, i) => String(i)} loading={ledgerLoading} dataSource={ledger?.rows || []}
          pagination={false} bordered size="small" scroll={{ y: 480 }}
          columns={[
            { title: '日期', dataIndex: 'date', width: 110 },
            { title: '凭证号', dataIndex: 'voucher_no', width: 90, render: (v, r: any) => v ? <a onClick={() => { setLedger(null); onOpenVoucher?.(r.voucher_id); }}>{v}</a> : '' },
            { title: '科目编码', dataIndex: 'account_code', width: 120 },
            { title: '摘要', dataIndex: 'summary' },
            { title: '状态', dataIndex: 'voucher_status', width: 76, render: (v) => v ? ({ DRAFT: '草稿', AUDITED: '审核', POSTED: '记账' } as any)[v] || v : '' },
            { title: '借方', dataIndex: 'debit', align: 'right', width: 120, render: (v) => v ? Number(v).toFixed(2) : '' },
            { title: '贷方', dataIndex: 'credit', align: 'right', width: 120, render: (v) => v ? Number(v).toFixed(2) : '' },
            { title: '方向', dataIndex: 'direction', width: 65, align: 'center' },
            { title: '余额', dataIndex: 'balance', align: 'right', width: 130, render: (v) => Number(v || 0).toFixed(2) },
          ]}
        />
      </Modal>
    </Card>
  );
};
