import axios from 'axios';

export const api = axios.create({
  baseURL: ((import.meta as any).env?.VITE_API_BASE_URL || '') + '/api/v1',
  timeout: 60000,
  withCredentials: true,
});
