import axios from 'axios';

export const api = axios.create({
  // The frontend reverse proxy owns the API route in every environment.
  // Keeping requests same-origin avoids stale production hosts and CORS failures.
  baseURL: '/api/v1',
  timeout: 60000,
  withCredentials: true,
});
