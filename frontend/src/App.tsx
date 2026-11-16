import React, { useEffect, useMemo, useState } from 'react';
import { Layout, Menu, Tabs, Tag, Space, Table, Card, Select, Button, message, Badge, Tooltip, Alert } from 'antd';
import {
  EditOutlined, BankOutlined, AccountBookOutlined, UnorderedListOutlined,
  BarChartOutlined, SwapOutlined, CalendarOutlined, ThunderboltOutlined,
  HomeOutlined, SafetyCertificateOutlined, FileSearchOutlined, SettingOutlined,
  RightOutlined, CheckCircleOutlined, DatabaseOutlined, UserOutlined, LogoutOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from './api';
import { VoucherEditor } from './pages/VoucherEditor';
import { BankStatements } from './pages/BankStatements';
import { TrialBalance } from './pages/TrialBalance';
import { FinancialReports } from './pages/FinancialReports';
import { AuxiliaryBalances } from './pages/AuxiliaryBalances';
import { AccountSettings } from './pages/AccountSettings';
import { Contracts } from './pages/Contracts';
import { LoginScreen, PasswordChange } from './pages/LoginScreen';
import { UserManagement } from './pages/UserManagement';
import './app.css';

const { Header, Content } = Layout;

const baseModuleItems = [
  { key: 'home', icon: <HomeOutlined />, label: '业务导航' },
  { key: 'accounting', icon: <EditOutlined />, label: '账务处理' },
  { key: 'reports', icon: <BarChartOutlined />, label: '财务报表' },
  { key: 'bank', icon: <BankOutlined />, label: '银行对账' },
  { key: 'arap', icon: <SwapOutlined />, label: '往来核算' },
  { key: 'contract', icon: <FileSearchOutlined />, label: '合同管理' },
  { key: 'settings', icon: <SettingOutlined />, label: '系统设置' },
];

const moduleDefaults: Record<string, string> = {
  home: 'home', accounting: 'voucher_new', reports: 'financial_reports', bank: 'statements',
  arap: 'arap', contract: 'contract', settings: 'settings', users: 'users',
};

function buildPeriods(current?: string) {
  const base = /^\d{4}-\d{2}$/.test(current || '') ? dayjs(`${current}-01`) : dayjs();
  return Array.from({ length: 12 }, (_, i) => base.startOf('year').add(i, 'month').format('YYYY-MM'));
}

function WorkflowHome({ company, period, voucherCount, go }: any) {
  const steps = [
    { key: 'voucher_new', icon: <EditOutlined />, title: '凭证录入', note: '键盘连续录入' },
    { key: 'voucher_list', icon: <SafetyCertificateOutlined />, title: '凭证审核', note: '查询与检查' },
    { key: 'voucher_list', icon: <CheckCircleOutlined />, title: '凭证记账', note: `${voucherCount} 张凭证` },
  ];
  const shortcuts = [
    { key: 'voucher_list', icon: <UnorderedListOutlined />, title: '凭证查询' },
    { key: 'trial_balance', icon: <AccountBookOutlined />, title: '科目余额表' },
    { key: 'trial_balance', icon: <DatabaseOutlined />, title: '明细分类账' },
    { key: 'financial_reports', icon: <BarChartOutlined />, title: '财务报表' },
  ];
  return <div className="workflow-page">
    <div className="page-caption"><div><b>业务导航</b><span>{company}</span></div><Tag>{period} 会计期间</Tag></div>
    <Card className="workflow-card" bordered={false}>
      <div className="operator-node"><div className="round-icon"><HomeOutlined /></div><b>操作员</b></div>
      <div className="workflow-line">
        {steps.map((step: any, index) => <React.Fragment key={`${step.key}-${index}`}>
          {index > 0 && <RightOutlined className="flow-arrow" />}
          <button className="flow-step" onClick={() => go(step.key)}>
            <span className="flow-step-icon">{step.icon}</span><b>{step.title}</b><small>{step.note}</small>
          </button>
        </React.Fragment>)}
      </div>
      <div className="shortcut-line">
        {shortcuts.map((item) => <button key={item.title} onClick={() => go(item.key)}>
          <span>{item.icon}</span><b>{item.title}</b>
        </button>)}
      </div>
    </Card>
    <div className="notice-strip"><Badge status="processing" /> 实时账簿模式：保存凭证后立即更新余额表和财务报表，无需等待月末批处理。</div>
  </div>;
}

export default function App() {
  const [user, setUser] = useState<any>(undefined);
  const [ctx, setCtx] = useState<any>(null);
  const [bootstrapError, setBootstrapError] = useState('');
  const [bootstrapLoading, setBootstrapLoading] = useState(false);
  const [selectedSetId, setSelectedSetId] = useState(() => localStorage.getItem('boshite_cod_account_set_id') || localStorage.getItem('ge_account_set_id') || '00000000-0000-0000-0000-000000000001');
  const [selectedPeriod, setSelectedPeriod] = useState('');
  const [moduleKey, setModuleKey] = useState('home');
  const [activeKey, setActiveKey] = useState('home');
  const [refreshTick, setRefreshTick] = useState(0);
  const [vouchers, setVouchers] = useState<any[]>([]);

  useEffect(() => { api.get('/auth/me').then((r) => setUser(r.data)).catch(() => setUser(null)); }, []);

  const loadBootstrap = async (targetSetId?: string) => {
    setBootstrapLoading(true);
    setBootstrapError('');
    try {
      const res = await api.get('/bootstrap', { params: { account_set_id: targetSetId || selectedSetId } });
      setCtx(res.data);
      if (res.data?.account_set?.id && res.data.account_set.id !== selectedSetId) {
        localStorage.setItem('boshite_cod_account_set_id', res.data.account_set.id);
        setSelectedSetId(res.data.account_set.id);
      }
      setSelectedPeriod((old) => old || res.data?.account_set?.current_period || dayjs().format('YYYY-MM'));
    } catch (e: any) {
      setCtx(null);
      if (e?.response?.status === 401) {
        setUser(null);
        message.warning('登录状态已失效，请重新登录');
        return;
      }
      setBootstrapError(e?.response?.data?.detail || e?.message || '工作台数据加载失败');
    } finally {
      setBootstrapLoading(false);
    }
  };
  const loadVouchers = async (setId: string, period: string) => {
    const res = await api.get('/vouchers', { params: { account_set_id: setId, period } });
    setVouchers(res.data);
  };
  useEffect(() => { if (user && !user.must_change_password) loadBootstrap(selectedSetId); }, [selectedSetId, user]);
  useEffect(() => { if (ctx?.account_set?.id && selectedPeriod) loadVouchers(ctx.account_set.id, selectedPeriod); }, [ctx, selectedPeriod, refreshTick]);

  const setId = ctx?.account_set?.id;
  const periods = useMemo(() => buildPeriods(ctx?.account_set?.current_period), [ctx?.account_set?.current_period]);
  const go = (key: string) => {
    setActiveKey(key);
    if (['voucher_new', 'voucher_list', 'trial_balance'].includes(key)) setModuleKey('accounting');
    else if (key === 'financial_reports') setModuleKey('reports');
    else if (key === 'statements') setModuleKey('bank');
    else setModuleKey(key);
  };
  const switchModule = ({ key }: { key: string }) => { setModuleKey(key); setActiveKey(moduleDefaults[key]); };
  const handleSwitchAccountSet = (id: string) => { localStorage.setItem('boshite_cod_account_set_id', id); setSelectedSetId(id); setSelectedPeriod(''); };
  const handleCarryForwardPnL = async () => {
    try {
      await api.post('/vouchers/carry-forward', null, { params: { account_set_id: setId, period: selectedPeriod } });
      message.success('期末损益结转凭证生成成功'); setRefreshTick((t) => t + 1);
    } catch (e: any) { message.error(e?.response?.data?.detail || '结转失败'); }
  };
  const changeVoucherStatus = async (voucher: any, action: string) => {
    const actionName: Record<string, string> = { AUDIT: '审核', UNAUDIT: '反审核', POST: '记账', UNPOST: '反记账' };
    try {
      await api.patch(`/vouchers/${voucher.id}/status`, { action });
      message.success(`${voucher.voucher_word}-${voucher.voucher_no} ${actionName[action]}成功`);
      setRefreshTick((t) => t + 1);
    } catch (e: any) { message.error(e?.response?.data?.detail || `${actionName[action]}失败`); }
  };
  const deleteVoucher = async (voucher: any) => {
    try {
      await api.delete(`/vouchers/${voucher.id}`);
      message.success(`${voucher.voucher_word}-${voucher.voucher_no} 已删除`);
      setRefreshTick((t) => t + 1);
    } catch (e: any) { message.error(e?.response?.data?.detail || '删除失败'); }
  };

  if (user === undefined) return <div className="app-loading">正在验证登录状态…</div>;
  if (!user) return <LoginScreen onLogin={setUser} />;
  if (user.must_change_password) return <PasswordChange user={user} onChanged={() => setUser({ ...user, must_change_password: false })} />;
  if (!ctx && bootstrapError) return <div className="app-loading app-load-failed">
    <Alert type="error" showIcon message="工作台加载失败" description={bootstrapError} />
    <Space>
      <Button type="primary" loading={bootstrapLoading} onClick={() => loadBootstrap(selectedSetId)}>重新加载</Button>
      <Button onClick={() => { setBootstrapError(''); setUser(null); }}>返回登录</Button>
    </Space>
  </div>;
  if (!ctx) return <div className="app-loading">正在加载博士特套账Cod…</div>;
  const accountSets = ctx?.account_sets || (ctx?.account_set ? [ctx.account_set] : []);
  const moduleItems = user.role === 'ADMIN' ? [...baseModuleItems, { key: 'users', icon: <UserOutlined />, label: '用户权限' }] : baseModuleItems;

  const contentItems = [
    { key: 'home', label: '业务导航', children: <WorkflowHome company={ctx.account_set.company_name} period={selectedPeriod} voucherCount={vouchers.length} go={go} /> },
    { key: 'voucher_new', label: '凭证录入', children: <VoucherEditor key={`ve-${setId}-${selectedPeriod}`} accountSetId={setId} period={selectedPeriod} accounts={ctx.accounts} agents={ctx.agents} onSaved={() => setRefreshTick((t) => t + 1)} /> },
    { key: 'voucher_list', label: '凭证查询', children: <Card title={`记账凭证序时簿 · ${selectedPeriod}`} extra={<Space><Button size="small">范围</Button><Button size="small">联查</Button><Button size="small">求和</Button><Button size="small">导出</Button><Button size="small">打印</Button></Space>}>
      <Table rowKey="id" dataSource={vouchers} size="small" bordered pagination={{ pageSize: 20 }} columns={[
        { title: '凭证号', render: (_, r: any) => <a>{r.voucher_word}-{r.voucher_no}</a>, width: 90 },
        { title: '日期', dataIndex: 'voucher_date', width: 105 },
        { title: '摘要 / 会计科目', render: (_, r: any) => r.entries?.map((e: any) => <div key={e.id} className="entry-line"><span>{e.summary}</span><Tag>{e.account_code}</Tag></div>) },
        { title: '借方', align: 'right' as const, width: 120, render: (_: any, r: any) => r.entries?.reduce((n: number, e: any) => n + e.debit_amount, 0).toFixed(2) },
        { title: '贷方', align: 'right' as const, width: 120, render: (_: any, r: any) => r.entries?.reduce((n: number, e: any) => n + e.credit_amount, 0).toFixed(2) },
        { title: '状态', dataIndex: 'status', width: 86, render: (s: string) => {
          const map: any = { DRAFT: ['草稿', 'default'], AUDITED: ['已审核', 'blue'], POSTED: ['已记账', 'green'] };
          return <Tag color={map[s]?.[1]}>{map[s]?.[0] || s}</Tag>;
        } },
        { title: '操作', width: 210, render: (_: any, r: any) => <Space size={4}>
          {r.status === 'DRAFT' && <><Button size="small" onClick={() => changeVoucherStatus(r, 'AUDIT')}>审核</Button><Button size="small" danger onClick={() => deleteVoucher(r)}>删除</Button></>}
          {r.status === 'AUDITED' && <><Button size="small" type="primary" onClick={() => changeVoucherStatus(r, 'POST')}>记账</Button><Button size="small" onClick={() => changeVoucherStatus(r, 'UNAUDIT')}>反审核</Button></>}
          {r.status === 'POSTED' && <Button size="small" onClick={() => changeVoucherStatus(r, 'UNPOST')}>反记账</Button>}
        </Space> },
      ]} />
    </Card> },
    { key: 'trial_balance', label: '科目余额表', children: <TrialBalance key={`tb-${setId}-${selectedPeriod}`} accountSetId={setId} period={selectedPeriod} refreshKey={refreshTick} onRefreshBootstrap={() => loadBootstrap(setId)} onOpenVoucher={() => go('voucher_list')} /> },
    { key: 'financial_reports', label: '财务报表', children: <FinancialReports key={`fr-${setId}-${selectedPeriod}`} accountSetId={setId} defaultPeriod={selectedPeriod} accounts={ctx.accounts} refreshKey={refreshTick} /> },
    { key: 'statements', label: '银行流水', children: <BankStatements key={`stmt-${setId}`} accountSetId={setId} bankAccounts={ctx.bank_accounts} accounts={ctx.accounts} onVoucherGenerated={() => setRefreshTick((t) => t + 1)} /> },
    { key: 'arap', label: '往来核算', children: <AuxiliaryBalances accountSetId={setId} period={selectedPeriod} /> },
    { key: 'contract', label: '合同管理', children: <Contracts accountSetId={setId} /> },
    { key: 'settings', label: '系统设置', children: <AccountSettings accountSetId={setId} /> },
    ...(user.role === 'ADMIN' ? [{ key: 'users', label: '用户与权限', children: <UserManagement accountSets={accountSets} /> }] : []),
  ];

  const logout = async () => { await api.post('/auth/logout'); setCtx(null); setUser(null); };

  return <Layout className="classic-shell">
    <Header className="brand-bar">
      <div className="brand"><span className="brand-mark">Cod</span><div><b>博士特套账Cod</b><small>标准财务套账工作台</small></div></div>
      <Space><span className="current-set-label">当前账套：</span><Select value={setId} onChange={handleSwitchAccountSet} className="set-picker" popupMatchSelectWidth={false} options={accountSets.map((s: any) => ({ value: s.id, label: s.company_name }))} /><Tag>{ctx.account_set.taxpayer_type === 'GENERAL' ? '一般纳税人' : '小规模纳税人'}</Tag></Space>
      <Space><CalendarOutlined /><Select value={selectedPeriod} onChange={setSelectedPeriod} className="period-picker" options={periods.map((p) => ({ value: p, label: p }))} /><Tooltip title="生成本期损益结转凭证"><Button icon={<ThunderboltOutlined />} onClick={handleCarryForwardPnL}>结转损益</Button></Tooltip><Tag icon={<UserOutlined />}>{user.display_name}</Tag><Button icon={<LogoutOutlined />} onClick={logout}>退出</Button></Space>
    </Header>
    <Menu mode="horizontal" selectedKeys={[moduleKey]} onClick={switchModule} items={moduleItems} className="module-nav" />
    <Content className="workspace">
      <Tabs type="card" activeKey={activeKey} onChange={go} items={contentItems} className="work-tabs" />
    </Content>
    <footer className="status-bar"><span>账套：{ctx.account_set.company_name}</span><span>期间：{selectedPeriod}</span><span>凭证：{vouchers.length} 张</span><span className="status-ready">● 系统就绪</span></footer>
  </Layout>;
}
