import axios from 'axios';

// Use the environment variable for the base URL, but provide a
// sensible default for local development. This allows the app to
// run locally without needing a .env file.
const apiBaseURL = import.meta.env.VITE_API_BASE_URL || 'https://amolicob.cloud/mealwhisperer';

// Create a dedicated axios instance for our API
const apiClient = axios.create({
  baseURL: apiBaseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default apiClient;
