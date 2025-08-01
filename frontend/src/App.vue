<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';

// --- State ---
const message = ref('Voice Transcription');
const isRecording = ref(false);
const transcript = ref('');
let recognition = null; // Will hold the SpeechRecognition instance
const recognitionSupported = ref(true);

// --- Methods ---
const toggleRecording = () => {
  if (!recognition) return;

  if (isRecording.value) {
    recognition.stop();
  } else {
    transcript.value = ''; // Clear previous transcript before starting
    recognition.start();
  }
};

onMounted(() => {
  // Initialize Speech Recognition API
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    recognitionSupported.value = false;
    console.error("Speech Recognition API is not supported in this browser.");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = false; // Only listen for a single utterance
  recognition.interimResults = true; // Show results as they are being spoken

  // Event handlers for the recognition service
  recognition.onstart = () => {
    isRecording.value = true;
  };

  // onend is the primary event for when the service is truly done.
  recognition.onend = () => {
    isRecording.value = false;
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    isRecording.value = false; // Ensure recording state is reset on error
  };

  recognition.onresult = (event) => {
    // Combine all results into a single transcript
    transcript.value = Array.from(event.results)
      .map(result => result[0].transcript)
      .join('');
  };
});

// Clean up the recognition service when the component is unmounted
onBeforeUnmount(() => {
  if (recognition) {
    recognition.abort();
  }
});
</script>

<template>
  <div id="app">
    <h1>{{ message }}</h1>
    <div class="transcription-controls">
      <button @click="toggleRecording" :disabled="!recognitionSupported">
        {{ isRecording ? 'Stop Recording' : 'Start Recording' }}
      </button>
      <p v-if="!recognitionSupported" class="support-error">
        Speech recognition is not supported in your browser.
      </p>
    </div>
    <div class="transcript-container" v-if="transcript">
      <h2>Transcript:</h2>
      <p>{{ transcript }}</p>
    </div>
  </div>
</template>

<style scoped>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  text-align: center;
  color: #2c3e50;
  margin-top: 60px;
}

.transcription-controls {
  margin: 20px 0;
}

.transcription-controls button {
  padding: 10px 20px;
  font-size: 16px;
  cursor: pointer;
}

.transcript-container {
  margin-top: 20px;
  padding: 15px;
  border: 1px solid #ddd;
  border-radius: 8px;
  text-align: left;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.support-error {
  color: #c0392b;
}
</style>
