import React, { useEffect, useState } from 'react';
import { Card, Tabs, Form, Switch, InputNumber, Button, message, Spin } from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { api } from '../api';

export const AccountSettings: React.FC<{ accountSetId: string }> = ({ accountSetId }) => {
  const [form] = Form.useForm(); const [loading, setLoading] = useState(true);
  useEffect(() => { setLoading(true); api.get('/account-set-settings', { params: { account_set_id: accountSetId } }).then(r => form.setFieldsValue(r.data)).finally(() => setLoading(false)); }, [accountSetId]);
  const save = async () => { await api.put('/account-set-settings', form.getFieldsValue(true), { params: { account_set_id: accountSetId } }); message.success('账套参数已保存'); };
  return <Card title="账套参数" extra={<Button type="primary" icon={<SaveOutlined />} onClick={save}>保存</Button>}>
    <Spin spinning={loading}><Form form={form} labelCol={{ span: 8 }} wrapperCol={{ span: 10 }}>
      <Tabs items={[
        { key: 'voucher', label: '凭证设置', children: <>
          <Form.Item name={['voucher_rules','allow_manual_no']} label="允许手工修改凭证号" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name={['voucher_rules','allow_unaudited_post']} label="未审核凭证允许记账" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name={['voucher_rules','auto_next_after_save']} label="保存后自动新增" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name={['voucher_rules','number_by_month']} label="凭证号按月连续" valuePropName="checked"><Switch /></Form.Item>
        </> },
        { key: 'display', label: '打印/显示', children: <>
          <Form.Item name={['display_rules','show_aux_tip']} label="显示辅助核算提示" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name={['display_rules','dense_tables']} label="使用紧凑账簿表格" valuePropName="checked"><Switch /></Form.Item>
        </> },
        { key: 'backup', label: '自动备份', children: <>
          <Form.Item name={['backup_rules','enabled']} label="启用自动备份" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name={['backup_rules','interval_days']} label="备份间隔（天）"><InputNumber min={1} max={90} /></Form.Item>
          <p style={{ textAlign:'center', color:'#84939b' }}>参数用于记录备份策略；桌面版备份执行器将在本机存储可用时启用。</p>
        </> },
      ]} />
    </Form></Spin>
  </Card>;
};
