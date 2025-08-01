<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';

const message = ref('Loading...');

onMounted(async () => {
  try {
    // Fetch data from the Python backend API
    const response = await axios.get('http://127.0.0.1:5000/api/hello');
    message.value = response.data.message;
  } catch (error) {
    console.error('Error fetching data from backend:', error);
    message.value = 'Failed to load message from backend.';
  }
});
</script>

<template>
  <div id="app">
    <h1>{{ message }}</h1>
  </div>
</template>

<style scoped>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  text-align: center;
  color: #2c3e50;
  margin-top: 60px;
}
</style>
