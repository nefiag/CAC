import React, { useState } from 'react';
import { Alert, Button, Card, Form, Input, Progress, Typography } from 'antd';
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
        body: JSON.stringify({ ...values, username: values.username.trim() }),
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
    <div className="login-brand"><span className="brand-mark">Cod</span><div><Typography.Title level={3}>博士特套账Cod</Typography.Title><span>标准财务套账工作台</span></div></div>
    <Typography.Paragraph type="secondary">使用操作员账号登录财务工作台</Typography.Paragraph>
    {error && <Alert type="error" message={error} showIcon />}
    <Form layout="vertical" onFinish={submit} requiredMark={false}>
      <Form.Item name="username" label="用户名" normalize={(value) => value?.replace(/^\s+/, '')} rules={[{ required: true, whitespace: true, message: '请输入用户名' }]}>
        <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" autoCapitalize="none" autoFocus />
      </Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
        <Input.Password size="large" prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
      </Form.Item>
      <Button htmlType="submit" type="primary" size="large" block loading={loading}>登录</Button>
      <div className="login-security-note"><LockOutlined /> 密码经加密传输，连续操作请勿共享账号</div>
    </Form>
  </Card></div>;
}

export function PasswordChange({ user, onChanged }: { user: any, onChanged: () => void }) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const newPassword = Form.useWatch('new_password', form) || '';
  const strength = Math.min(100, [newPassword.length >= 8, /[a-z]/.test(newPassword), /[A-Z]/.test(newPassword), /\d/.test(newPassword), /[^A-Za-z0-9]/.test(newPassword)].filter(Boolean).length * 20);
  const submit = async (values: any) => {
    setError(''); setLoading(true);
    try {
      const res = await fetch('/api/v1/auth/change-password', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password }),
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
  return <div className="login-shell"><Card className="login-card" title="首次登录 · 设置新密码">
    <Typography.Paragraph><b>{user.display_name}</b>，为保护账号安全，请修改初始密码后继续。</Typography.Paragraph>
    {error && <Alert type="error" message={error} showIcon />}
    <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
      <Form.Item name="current_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
        <Input.Password size="large" autoComplete="current-password" placeholder="请输入初始密码" autoFocus />
      </Form.Item>
      <Form.Item name="new_password" label="新密码" dependencies={['current_password']} rules={[
        { required: true, message: '请输入新密码' },
        { min: 8, message: '密码至少需要 8 个字符' },
        ({ getFieldValue }) => ({ validator(_, value) { return !value || value !== getFieldValue('current_password') ? Promise.resolve() : Promise.reject(new Error('新密码不能与当前密码相同')); } }),
      ]}>
        <Input.Password size="large" autoComplete="new-password" placeholder="至少 8 个字符" />
      </Form.Item>
      {newPassword && <div className="password-strength">
        <span>密码强度</span><Progress percent={strength} steps={5} showInfo={false} strokeColor={strength < 60 ? '#e49b23' : '#3b9a66'} />
        <small>{strength < 60 ? '建议混合大小写字母、数字和符号' : '密码强度良好'}</small>
      </div>}
      <Form.Item name="confirm_password" label="确认新密码" dependencies={['new_password']} rules={[
        { required: true, message: '请再次输入新密码' },
        ({ getFieldValue }) => ({ validator(_, value) { return !value || value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')); } }),
      ]}>
        <Input.Password size="large" autoComplete="new-password" placeholder="请再次输入新密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" size="large" block loading={loading}>保存并进入工作台</Button>
    </Form>
  </Card></div>;
}
