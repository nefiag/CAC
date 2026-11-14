import React, { useEffect, useState } from 'react';
import { Layout, Menu, Tabs, Tag, Space, Table, Card, Select, Button, message } from 'antd';
import {
  EditOutlined,
  BankOutlined,
  AccountBookOutlined,
  UnorderedListOutlined,
  BarChartOutlined,
  SwapOutlined,
  CalendarOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { api } from './api';
import { VoucherEditor } from './pages/VoucherEditor';
import { BankStatements } from './pages/BankStatements';
import { TrialBalance } from './pages/TrialBalance';
import { FinancialReports } from './pages/FinancialReports';

const { Header, Sider, Content } = Layout;

export default function App() {
  const [ctx, setCtx] = useState<any>(null);
  const [selectedSetId, setSelectedSetId] = useState<string>(
    () => localStorage.getItem('ge_account_set_id') || '00000000-0000-0000-0000-000000000001'
  );
  const [selectedPeriod, setSelectedPeriod] = useState<string>('2026-11');
  const [activeKey, setActiveKey] = useState('statements');
  const [refreshTick, setRefreshTick] = useState(0);
  const [vouchers, setVouchers] = useState<any[]>([]);

  const loadBootstrap = async (targetSetId?: string) => {
    const idToLoad = targetSetId || selectedSetId;
    const res = await api.get('/bootstrap', { params: { account_set_id: idToLoad } });
    setCtx(res.data);
    if (res.data?.account_set?.current_period && !selectedPeriod) {
      setSelectedPeriod(res.data.account_set.current_period);
    }
  };

  const loadVouchers = async (setId: string, period: string) => {
    const res = await api.get('/vouchers', { params: { account_set_id: setId, period } });
    setVouchers(res.data);
  };

  useEffect(() => {
    loadBootstrap(selectedSetId);
  }, [selectedSetId]);

  useEffect(() => {
    if (ctx?.account_set?.id) {
      loadVouchers(ctx.account_set.id, selectedPeriod || ctx.account_set.current_period);
    }
  }, [ctx, selectedPeriod, refreshTick]);

  const handleSwitchAccountSet = (newSetId: string) => {
    localStorage.setItem('ge_account_set_id', newSetId);
    setSelectedSetId(newSetId);
    setRefreshTick((t) => t + 1);
  };

  const handleCarryForwardPnL = async () => {
    try {
      await api.post('/vouchers/carry-forward', null, {
        params: { account_set_id: setId, period: selectedPeriod }
      });
      message.success('期末损益结转凭证生成成功！');
      setRefreshTick((t) => t + 1);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '结转失败');
    }
  };

  if (!ctx) return <div style={{ padding: 40 }}>正在加载晓会计 3.0 专业版工作台...</div>;

  const setId = ctx?.account_set?.id;
  const accountSets = ctx?.account_sets || (ctx?.account_set ? [ctx.account_set] : []);
  const periods = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11', '2026-12'];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark">
        <div style={{ height: 48, margin: 12, color: '#fff', fontWeight: 'bold', fontSize: 15, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.1)', borderRadius: 6 }}>
          晓会计 3.0 · REA 财务
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[activeKey]}
          onClick={(e) => setActiveKey(e.key)}
          items={[
            { key: 'statements', icon: <BankOutlined />, label: 'AI 银行对账单' },
            { key: 'voucher_new', icon: <EditOutlined />, label: '填制凭证 (键盘流)' },
            { key: 'voucher_list', icon: <UnorderedListOutlined />, label: '查凭证 (序时簿)' },
            { key: 'trial_balance', icon: <AccountBookOutlined />, label: '科目余额表 (三级联查)' },
            { key: 'financial_reports', icon: <BarChartOutlined />, label: '规范报表与结转' },
          ]}
        />
      </Sider>

      <Layout>
        {/* 晓会计经典顶栏：公司账套切换 + 会计期间切换 + 一键结转损益 */}
        <Header style={{ background: '#fff', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f0f0f0', height: 56 }}>
          <Space size="middle">
            <SwapOutlined style={{ color: '#1677ff' }} />
            <Select
              value={setId}
              onChange={handleSwitchAccountSet}
              style={{ width: 280, fontWeight: 'bold' }}
              options={accountSets.map((s: any) => ({
                value: s.id,
                label: s.company_name,
              }))}
            />
            <Tag color="blue">{ctx?.account_set?.taxpayer_type === 'GENERAL' ? '一般纳税人' : '小规模纳税人'}</Tag>
          </Space>
          
          <Space size="middle">
            <Space>
              <CalendarOutlined style={{ color: '#52c41a' }} />
              <span>会计期间：</span>
              <Select
                value={selectedPeriod}
                onChange={setSelectedPeriod}
                style={{ width: 110 }}
                options={periods.map((p) => ({ value: p, label: p }))}
              />
            </Space>
            <Button type="primary" ghost icon={<ThunderboltOutlined />} size="small" onClick={handleCarryForwardPnL}>
              期末结转损益
            </Button>
          </Space>
        </Header>

        <Content style={{ margin: 12 }}>
          <Tabs
            type="card"
            activeKey={activeKey}
            onChange={setActiveKey}
            items={[
              {
                key: 'statements',
                label: 'AI 银行对账单 (智能生单)',
                children: (
                  <BankStatements
                    key={`stmt-${setId}`}
                    accountSetId={setId}
                    bankAccounts={ctx.bank_accounts}
                    accounts={ctx.accounts}
                    onVoucherGenerated={() => setRefreshTick((t) => t + 1)}
                  />
                ),
              },
              {
                key: 'voucher_new',
                label: '填制凭证',
                children: (
                  <VoucherEditor
                    key={`ve-${setId}-${selectedPeriod}`}
                    accountSetId={setId}
                    period={selectedPeriod}
                    accounts={ctx.accounts}
                    onSaved={() => setRefreshTick((t) => t + 1)}
                  />
                ),
              },
              {
                key: 'voucher_list',
                label: '查凭证',
                children: (
                  <Card title={`记账凭证序时簿（${ctx?.account_set?.company_name} · ${selectedPeriod}）`}>
                    <Table
                      rowKey="id"
                      dataSource={vouchers}
                      size="small"
                      columns={[
                        { title: '凭证号', render: (_, r) => <Tag color="blue">{r.voucher_word}-{r.voucher_no}</Tag>, width: 100 },
                        { title: '日期', dataIndex: 'voucher_date', width: 120 },
                        {
                          title: '分录明细摘要与科目',
                          render: (_, r) =>
                            r.entries?.map((e: any) => (
                              <div key={e.id} style={{ fontSize: 12, padding: '2px 0' }}>
                                <b>[{e.summary}]</b> &nbsp; 科目: <Tag>{e.account_code}</Tag> — 借方: <b>{e.debit_amount.toFixed(2)}</b> / 贷方: <b>{e.credit_amount.toFixed(2)}</b>
                              </div>
                            )),
                        },
                        { title: '状态', dataIndex: 'status', width: 90, render: (s) => <Tag color="green">{s}</Tag> },
                      ]}
                    />
                  </Card>
                ),
              },
              {
                key: 'trial_balance',
                label: '科目余额表',
                children: (
                  <TrialBalance
                    key={`tb-${setId}-${selectedPeriod}`}
                    accountSetId={setId}
                    period={selectedPeriod}
                    refreshKey={refreshTick}
                    onRefreshBootstrap={() => loadBootstrap(setId)}
                  />
                ),
              },
              {
                key: 'financial_reports',
                label: '财务规范报表与结转',
                children: (
                  <FinancialReports
                    key={`fr-${setId}-${selectedPeriod}`}
                    accountSetId={setId}
                    defaultPeriod={selectedPeriod}
                    accounts={ctx.accounts}
                    refreshKey={refreshTick}
                  />
                ),
              },
            ]}
          />
        </Content>
      </Layout>
    </Layout>
  );
}
