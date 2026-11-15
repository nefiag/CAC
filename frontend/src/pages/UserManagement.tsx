import React, { useEffect, useState } from 'react';
import { Button, Form, Input, Modal, Select, Switch, Table, Tag, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { api } from '../api';

const roles: any = { ADMIN: ['管理员', 'red'], ACCOUNTANT: ['会计', 'blue'], VIEWER: ['只读', 'default'] };

export function UserManagement({ accountSets }: { accountSets: any[] }) {
  const [users, setUsers] = useState<any[]>([]);
  const [editing, setEditing] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const load = () => api.get('/users').then((r) => setUsers(r.data));
  useEffect(() => { void load(); }, []);
  const edit = (user?: any) => { setEditing(user || null); form.setFieldsValue(user || { role: 'ACCOUNTANT', is_active: true, account_set_ids: [] }); setOpen(true); };
  const save = async () => {
    const values = await form.validateFields();
    try {
      if (editing) await api.put(`/users/${editing.id}`, { ...editing, ...values });
      else await api.post('/users', values);
      message.success(editing ? '用户已更新' : '用户已创建'); setOpen(false); form.resetFields(); load();
    } catch (e: any) { message.error(e?.response?.data?.detail || '保存失败'); }
  };
  return <>
    <div className="page-caption"><div><b>用户与权限</b><span>管理操作员、角色和可访问账套</span></div><Button type="primary" icon={<PlusOutlined />} onClick={() => edit()}>新增用户</Button></div>
    <Table rowKey="id" dataSource={users} bordered size="small" columns={[
      { title: '用户名', dataIndex: 'username' }, { title: '姓名', dataIndex: 'display_name' },
      { title: '角色', dataIndex: 'role', render: (v) => <Tag color={roles[v]?.[1]}>{roles[v]?.[0] || v}</Tag> },
      { title: '账套权限', dataIndex: 'account_set_ids', render: (ids: string[], row: any) => row.role === 'ADMIN' ? '全部账套' : ids.map((id) => <Tag key={id}>{accountSets.find((s) => s.id === id)?.company_name || id}</Tag>) },
      { title: '状态', dataIndex: 'is_active', render: (v) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '操作', render: (_: any, row: any) => <Button size="small" onClick={() => edit(row)}>编辑</Button> },
    ]} />
    <Modal title={editing ? '编辑用户' : '新增用户'} open={open} onOk={save} onCancel={() => setOpen(false)} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
        <Form.Item name="display_name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="password" label={editing ? '重置密码（留空则不修改）' : '初始密码'} rules={editing ? [] : [{ required: true, min: 8 }]}><Input.Password /></Form.Item>
        <Form.Item name="role" label="角色" rules={[{ required: true }]}><Select options={[{ value: 'ADMIN', label: '管理员' }, { value: 'ACCOUNTANT', label: '会计（可录入、审核、记账）' }, { value: 'VIEWER', label: '只读（仅查询和报表）' }]} /></Form.Item>
        <Form.Item name="account_set_ids" label="可访问账套"><Select mode="multiple" options={accountSets.map((s) => ({ value: s.id, label: s.company_name }))} /></Form.Item>
        <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  </>;
}
