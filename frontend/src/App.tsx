import React, { useEffect, useState } from 'react';
import { Layout, Menu, Tabs, Tag, Space, Table, Card, Select } from 'antd';
import {
  EditOutlined,
  BankOutlined,
  AccountBookOutlined,
  UnorderedListOutlined,
  BarChartOutlined,
  SwapOutlined,
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
  const [activeKey, setActiveKey] = useState('statements');
  const [refreshTick, setRefreshTick] = useState(0);
  const [vouchers, setVouchers] = useState<any[]>([]);

  const loadBootstrap = async (targetSetId?: string) => {
    const idToLoad = targetSetId || selectedSetId;
    const res = await api.get('/bootstrap', { params: { account_set_id: idToLoad } });
    setCtx(res.data);
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
      loadVouchers(ctx.account_set.id, ctx.account_set.current_period);
    }
  }, [ctx, refreshTick]);

  const handleSwitchAccountSet = (newSetId: string) => {
    localStorage.setItem('ge_account_set_id', newSetId);
    setSelectedSetId(newSetId);
    setRefreshTick((t) => t + 1);
  };

  if (!ctx) return <div style={{ padding: 40 }}>正在初始化 REA 双核财务工作台...</div>;

  const setId = ctx?.account_set?.id;
  const period = ctx?.account_set?.current_period;
  const accountSets = ctx?.account_sets || (ctx?.account_set ? [ctx.account_set] : []);

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={210} theme="dark">
        <div style={{ height: 48, margin: 12, color: '#fff', fontWeight: 'bold', fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.1)', borderRadius: 6 }}>
          REA 智能云财务
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[activeKey]}
          onClick={(e) => setActiveKey(e.key)}
          items={[
            { key: 'statements', icon: <BankOutlined />, label: 'AI 银行对账单' },
            { key: 'voucher_new', icon: <EditOutlined />, label: '录凭证' },
            { key: 'voucher_list', icon: <UnorderedListOutlined />, label: '查凭证' },
            { key: 'trial_balance', icon: <AccountBookOutlined />, label: '科目余额表' },
            { key: 'financial_reports', icon: <BarChartOutlined />, label: '财务规范报表' },
          ]}
        />
      </Sider>

      <Layout>
        <Header style={{ background: '#fff', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f0f0f0', height: 52 }}>
          <Space>
            <SwapOutlined style={{ color: '#1677ff' }} />
            <Select
              value={setId}
              onChange={handleSwitchAccountSet}
              style={{ width: 290, fontWeight: 'bold' }}
              options={accountSets.map((s: any) => ({
                value: s.id,
                label: s.company_name,
              }))}
            />
            <Tag color="blue">{ctx?.account_set?.taxpayer_type === 'GENERAL' ? '一般纳税人' : '小规模纳税人'}</Tag>
            <Tag color="green">REA 双核驱动</Tag>
          </Space>
          <Space>
            <span>当前会计期间：</span>
            <Tag color="geekblue">{period}</Tag>
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
                label: 'AI 银行对账单',
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
                label: '录凭证',
                children: (
                  <VoucherEditor
                    key={`ve-${setId}`}
                    accountSetId={setId}
                    period={period}
                    accounts={ctx.accounts}
                    onSaved={() => setRefreshTick((t) => t + 1)}
                  />
                ),
              },
              {
                key: 'voucher_list',
                label: '查凭证',
                children: (
                  <Card title={`记账凭证列表（${ctx?.account_set?.company_name} · ${period}）`}>
                    <Table
                      rowKey="id"
                      dataSource={vouchers}
                      size="small"
                      columns={[
                        { title: '凭证号', render: (_, r) => <Tag color="blue">{r.voucher_word}-{r.voucher_no}</Tag>, width: 100 },
                        { title: '日期', dataIndex: 'voucher_date', width: 120 },
                        {
                          title: '分录明细',
                          render: (_, r) =>
                            r.entries?.map((e: any) => (
                              <div key={e.id} style={{ fontSize: 12 }}>
                                [{e.summary}] {e.account_code} — 借: {e.debit_amount.toFixed(2)} / 贷: {e.credit_amount.toFixed(2)}
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
                    key={`tb-${setId}`}
                    accountSetId={setId}
                    period={period}
                    refreshKey={refreshTick}
                    onRefreshBootstrap={() => loadBootstrap(setId)}
                  />
                ),
              },
              {
                key: 'financial_reports',
                label: '财务规范报表',
                children: (
                  <FinancialReports
                    key={`fr-${setId}`}
                    accountSetId={setId}
                    defaultPeriod={period}
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
