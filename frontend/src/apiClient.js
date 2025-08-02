import axios from 'axios';

// Create a dedicated axios instance for our API
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/',
  headers: {
    'Content-Type': 'application/json',
  },
});

export default apiClient;
