import React, { useState } from 'react';
import { Alert, Button, Card, Form, Input, Typography } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';

export function LoginScreen({ onLogin }: { onLogin: (user: any) => void }) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async (values: any) => {
    setLoading(true); setError('');
    try {
      // Login is deliberately same-origin. Native fetch avoids browser/proxy
      // adapters treating the Cloudflare endpoint as a cross-site request.
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || `登录失败（HTTP ${res.status}）`);
      onLogin(data);
    }
    catch (e: any) {
      setError(e?.message ? `登录失败：${e.message}` : '登录失败：浏览器未能连接服务器');
    }
    finally { setLoading(false); }
  };
  return <div className="login-shell"><Card className="login-card" bordered={false}>
    <div className="login-brand"><span className="brand-mark">CX</span><div><Typography.Title level={3}>Coxiaoac</Typography.Title><span>经典财务工作台</span></div></div>
    <Typography.Paragraph type="secondary">请输入操作员账号和密码</Typography.Paragraph>
    {error && <Alert type="error" message={error} showIcon />}
    <Form layout="vertical" onFinish={submit} requiredMark={false}>
      <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}><Input size="large" prefix={<UserOutlined />} autoFocus /></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}><Input.Password size="large" prefix={<LockOutlined />} /></Form.Item>
      <Button htmlType="submit" type="primary" size="large" block loading={loading}>登录</Button>
    </Form>
  </Card></div>;
}

export function PasswordChange({ user, onChanged }: { user: any, onChanged: () => void }) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async (values: any) => {
    setError(''); setLoading(true);
    try {
      const res = await fetch('/api/v1/auth/change-password', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || `修改失败（HTTP ${res.status}）`);
      onChanged();
    }
    catch (e: any) {
      setError(e?.message ? `修改失败：${e.message}` : '修改失败：浏览器未能连接服务器');
    }
    finally { setLoading(false); }
  };
  return <div className="login-shell"><Card className="login-card" title="首次登录 · 修改密码">
    <Typography.Paragraph>{user.display_name}，请修改初始密码后继续。</Typography.Paragraph>
    {error && <Alert type="error" message={error} showIcon />}
    <Form layout="vertical" onFinish={submit} requiredMark={false}>
      <Form.Item name="current_password" label="当前密码" rules={[{ required: true }]}><Input.Password /></Form.Item>
      <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 8, message: '至少 8 个字符' }]}><Input.Password /></Form.Item>
      <Button type="primary" htmlType="submit" block loading={loading}>保存新密码</Button>
    </Form>
  </Card></div>;
}
