import axios from 'axios';

export const api = axios.create({
  baseURL: ((import.meta as any).env?.VITE_API_BASE_URL || 'https://api.bstks.cn') + '/api/v1',
  timeout: 60000,
});
