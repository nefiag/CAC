import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#267a9f',
          borderRadius: 3,
          fontSize: 15,
          fontSizeSM: 14,
          fontSizeLG: 17,
          controlHeight: 34,
          controlHeightSM: 28,
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
