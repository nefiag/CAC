import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Button, Space, message } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { api } from '../api';

export const AuxiliaryBalances: React.FC<{ accountSetId: string; period: string }> = ({ accountSetId, period }) => {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true);
    try { setRows((await api.get('/reports/auxiliary-balances', { params: { account_set_id: accountSetId, end_period: period } })).data); }
    catch { message.error('往来余额加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [accountSetId, period]);
  return <Card title={`往来单位余额表 · 截至 ${period}`} extra={<Space><Tag>仅统计已记账凭证</Tag><Button icon={<SyncOutlined />} onClick={load}>刷新</Button></Space>}>
    <Table rowKey={(r) => `${r.dimension}-${r.agent_id}-${r.account_code}`} dataSource={rows} loading={loading} bordered size="small"
      locale={{ emptyText: '暂无带客户或供应商辅助核算的已记账分录' }}
      columns={[
        { title: '类别', dataIndex: 'dimension', width: 100, render: (v) => <Tag color={v === 'CUSTOMER' ? 'blue' : 'orange'}>{v === 'CUSTOMER' ? '客户' : v === 'VENDOR' ? '供应商' : v}</Tag> },
        { title: '编码', dataIndex: 'agent_code', width: 110 },
        { title: '往来单位', dataIndex: 'agent_name' },
        { title: '科目', dataIndex: 'account_code', width: 120 },
        { title: '借方余额', dataIndex: 'debit_balance', align: 'right', width: 140, render: (v) => Number(v).toFixed(2) },
        { title: '贷方余额', dataIndex: 'credit_balance', align: 'right', width: 140, render: (v) => Number(v).toFixed(2) },
        { title: '最后发生日', dataIndex: 'last_date', width: 120 },
      ]} />
  </Card>;
};
