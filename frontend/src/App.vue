<script setup>
import { ref, onMounted, onBeforeUnmount, computed, nextTick } from 'vue';
import axios from 'axios';

// --- State ---
const isRecording = ref(false);
const isProcessing = ref(false); // To give user feedback during API call
const transcript = ref('');
const aiResponse = ref('');
const confirmationState = ref(null); // Holds { action, details } for any pending action
const dailyLog = ref(null);
const editingEntryId = ref(null); // ID of the entry being edited
const isFoodModalVisible = ref(false);
const editingFood = ref(null); // Holds {id, name, calories} for the food being edited
const editingQuantity = ref(null); // The value in the edit input
const viewedDate = ref(new Date()); // The date currently being viewed by the user
let confirmationTimer = null; // Holds the timeout ID
let recognition = null; // Will hold the SpeechRecognition instance
const recognitionSupported = ref(true);

const formattedViewedDate = computed(() => {
  // Provides a user-friendly, locale-aware string for the date header
  return viewedDate.value.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
});

// --- Methods ---
const toggleRecording = () => {
  if (!recognition || isProcessing.value) return;

  if (isRecording.value) {
    recognition.stop();
  } else {
    transcript.value = ''; // Clear previous transcript before starting
    aiResponse.value = ''; // Clear previous AI response
    confirmationState.value = null; // Clear previous confirmation state
    if (confirmationTimer) clearTimeout(confirmationTimer); // Clear any pending timer
    recognition.start();
  }
};

const sendPromptToBackend = async () => {
  if (!transcript.value.trim()) return; // Don't send empty transcripts

  isProcessing.value = true;
  try {
    const response = await axios.post('http://127.0.0.1:5000/api/prompt', {
      text: transcript.value,
    });
    console.log('Backend response:', response.data);

    const { action, details, response_text } = response.data;
    aiResponse.value = response_text;

    // Handle the response from the backend
    if (['readback_required', 'explicit_confirmation_required', 'meal_clarification_required'].includes(action)) {
      confirmationState.value = { action, details };
      if (action === 'readback_required') {
        // Start a 5-second timer to auto-confirm the log.
        confirmationTimer = setTimeout(() => {
          if (confirmationState.value) { // Ensure it wasn't cancelled
            confirmLog();
          }
        }, 5000);
      }
    } else {
      confirmationState.value = null; // Clear any old confirmation
    }

  } catch (error) {
    console.error('Error getting AI response:', error);
    aiResponse.value = 'Sorry, an error occurred. Please try again.';
  } finally {
    isProcessing.value = false;
  }
};

const confirmLog = async () => {
  if (!confirmationState.value) return;

  isProcessing.value = true;
  try {
    const response = await axios.post('http://127.0.0.1:5000/api/prompt', {
      action: 'confirm_log',
      details: confirmationState.value.details,
    });
    console.log('Confirmation response:', response.data);
    aiResponse.value = response.data.response_text;
    // If the log was finalized, refresh the daily log display
    if (response.data.action === 'log_finalized') {
      await fetchDailyLog();
    }
  } catch (error) {
    console.error('Error confirming log:', error);
    aiResponse.value = 'Sorry, could not confirm the log.';
  } finally {
    // Clear confirmation state after action is complete
    confirmationState.value = null;
    isProcessing.value = false;
  }
};

const cancelLog = () => {
  if (confirmationTimer) clearTimeout(confirmationTimer); // Stop any auto-confirm
  confirmationState.value = null;
  aiResponse.value = "Okay, cancelled.";
  // Briefly show the cancellation message before clearing it.
  setTimeout(() => {
      if (aiResponse.value === "Okay, cancelled.") aiResponse.value = '';
  }, 2000);
};

const submitMealClarification = async (meal) => {
  if (!confirmationState.value || !meal) return;

  isProcessing.value = true;
  const details = confirmationState.value.details;
  
  // Clear the old state
  confirmationState.value = null;

  try {
    const response = await axios.post('http://127.0.0.1:5000/api/prompt', {
      action: 'clarify_meal',
      details: details,
      meal: meal
    });

    const { action, details: newDetails, response_text } = response.data;
    aiResponse.value = response_text;

    // The response will now be a readback, explicit confirmation, or an error.
    if (action === 'readback_required' || action === 'explicit_confirmation_required') {
      confirmationState.value = { action, details: newDetails };
      if (action === 'readback_required') {
        confirmationTimer = setTimeout(() => { if (confirmationState.value) confirmLog(); }, 5000);
      }
    }
  } catch (error) {
    console.error('Error submitting meal clarification:', error);
    aiResponse.value = 'Sorry, an error occurred.';
  } finally {
    isProcessing.value = false;
  }
};

const changeDate = (days) => {
  const newDate = new Date(viewedDate.value);
  newDate.setDate(newDate.getDate() + days);
  viewedDate.value = newDate;
  fetchDailyLog(); // Fetch data for the new date
};

const editQuantity = (entry) => {
  editingEntryId.value = entry.id;
  editingQuantity.value = entry.quantity;
  // nextTick ensures the DOM is updated before we try to find and focus the input
  nextTick(() => {
    const inputEl = document.getElementById(`qty-input-${entry.id}`);
    if (inputEl) {
      inputEl.focus();
      inputEl.select();
    }
  });
};

const getApiDateString = (dateObj) => {
  const year = dateObj.getFullYear();
  const month = String(dateObj.getMonth() + 1).padStart(2, '0'); // Months are 0-indexed
  const day = String(dateObj.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const saveQuantity = async (entry) => {
  if (editingEntryId.value === null) return; // Avoids re-saving on blur after enter

  const originalQuantity = entry.quantity;
  const newQuantity = Number(editingQuantity.value);

  // Reset editing state immediately for better UX
  editingEntryId.value = null;
  editingQuantity.value = null;

  // Validate and check for changes before making an API call
  if (isNaN(newQuantity) || newQuantity < 1 || newQuantity > 100 || newQuantity === originalQuantity) {
    console.log("Validation failed or no change, reverting.");
    return;
  }

  try {
    const dateString = getApiDateString(viewedDate.value);
    await axios.patch(`http://127.0.0.1:5000/api/logs/${dateString}/entry/${entry.id}`, {
      quantity: newQuantity,
    });
    // Refresh the entire log to get updated totals
    await fetchDailyLog();
  } catch (error) {
    console.error("Error updating quantity:", error);
    alert("Failed to update quantity. Please try again.");
  }
};

const openFoodEditor = (entry) => {
  editingFood.value = {
    id: entry.food_id,
    name: entry.food,
    calories: entry.per_item_calories,
  };
  isFoodModalVisible.value = true;
};

const closeFoodEditor = () => {
  isFoodModalVisible.value = false;
  editingFood.value = null;
};

const saveFoodCalories = async () => {
  if (!editingFood.value) return;

  const newCalories = Number(editingFood.value.calories);
  if (isNaN(newCalories) || newCalories < 0 || newCalories > 5000) {
    alert("Please enter a valid calorie amount (0-5000).");
    return;
  }

  try {
    await axios.patch(`http://127.0.0.1:5000/api/foods/${editingFood.value.id}`, {
      calories: newCalories,
    });
    closeFoodEditor();
    // Refresh the daily log to show the updated calorie calculations
    await fetchDailyLog();
  } catch (error) {
    console.error("Error updating food calories:", error);
    alert("Failed to update calories. Please try again.");
  }
};

const fetchDailyLog = async () => {
  try {
    console.log("Attempting to fetch daily log...");
    // Correctly get the local date, not the UTC date from toISOString().
    // This prevents timezone-related off-by-one-day errors.
    const dateString = getApiDateString(viewedDate.value);
    const response = await axios.get(`http://127.0.0.1:5000/api/logs/${dateString}`);
    console.log("Successfully fetched data from backend:", response.data);
    dailyLog.value = response.data; // Always set the data

    if (response.data && Object.keys(response.data.meals).length > 0) {
      console.log("Log contains meals. Displaying table.");
    } else {
      console.log("Log is empty or contains no meals. Displaying 'no meals' message.");
    }
  } catch (error) {
    console.error("Error fetching today's log:", error);
  }
};

onMounted(async () => {
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
    // Send the final prompt to the backend
    sendPromptToBackend();
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

  // Fetch initial log data when the component mounts
  await fetchDailyLog();
});

// Clean up the recognition service when the component is unmounted
onBeforeUnmount(() => {
  if (recognition) {
    if (confirmationTimer) clearTimeout(confirmationTimer);
    recognition.abort();
  }
});
</script>

<template>
  <!-- Food Editor Modal -->
  <div v-if="isFoodModalVisible" class="modal-overlay" @click.self="closeFoodEditor">
    <div class="modal-content">
      <h3>Edit Food</h3>
      <div v-if="editingFood">
        <p class="food-name-display">{{ editingFood.name }}</p>
        <div class="modal-form-group">
          <label for="food-calories">Calories per serving:</label>
          <input id="food-calories" type="number" v-model="editingFood.calories" />
        </div>
        <div class="modal-actions">
          <button @click="saveFoodCalories" class="save-button">Save</button>
          <button @click="closeFoodEditor" class="cancel-button">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <div id="app">
    <div class="transcription-controls">
      <button @click="toggleRecording" :disabled="!recognitionSupported || isProcessing">
        {{ isRecording ? 'Stop Recording' : (isProcessing ? 'Processing...' : 'Start Recording') }}
      </button>
      <p v-if="!recognitionSupported" class="support-error">
        Speech recognition is not supported in your browser.
      </p>
    </div>
    <div class="transcript-container" v-if="transcript">
      <h2>Transcript:</h2>
      <p>{{ transcript }}</p>
    </div>
    <div class="ai-response-container" v-if="aiResponse">
      <h2>AI Response:</h2>
      <p>{{ aiResponse }}</p>
      <div v-if="confirmationState" class="confirmation-buttons">
        <!-- Explicit confirmation for high quantity -->
        <template v-if="confirmationState.action === 'explicit_confirmation_required'">
          <button @click="confirmLog" :disabled="isProcessing">Yes, Log It</button>
          <button @click="cancelLog" class="cancel-button">No, Cancel</button>
        </template>
        <!-- Meal clarification input -->
        <template v-else-if="confirmationState.action === 'meal_clarification_required'">
          <button @click="submitMealClarification('breakfast')">Breakfast</button>
          <button @click="submitMealClarification('lunch')">Lunch</button>
          <button @click="submitMealClarification('dinner')">Dinner</button>
          <button @click="submitMealClarification('snack')">Snack</button>
          <button @click="cancelLog" class="cancel-button">Cancel</button>
        </template>
        <!-- Default cancel for auto-confirm readback -->
        <template v-else>
          <button @click="cancelLog" class="cancel-button">Cancel</button>
        </template>
    </div>
    </div>
    <div class="daily-log-container" v-if="dailyLog">
      <div class="date-navigation">
        <button @click="changeDate(-1)" class="nav-button">&lt;</button>
        <h2 class="date-header">{{ formattedViewedDate }}</h2>
        <button @click="changeDate(1)" class="nav-button">&gt;</button>
      </div>
      <h3 class="daily-total">Total: {{ dailyLog.total_daily_calories }} calories</h3>
      <div class="meal-swimlanes" v-if="Object.keys(dailyLog.meals).length > 0">
        <div v-for="(mealData, mealName) in dailyLog.meals" :key="mealName" class="meal-lane">
          <h3 class="meal-header">
            <span>{{ mealName }}</span>
            <span class="meal-total">{{ mealData.total_meal_calories }} calories</span>
          </h3>
          <div class="meal-entries">
            <div class="entry-row header-row">
              <div class="col-qty">Qty</div>
              <div class="col-food">Food</div>
              <div class="col-cals">Calories</div>
            </div>
            <div v-for="(entry, index) in mealData.entries" :key="index" class="entry-row">
              <div class="col-qty">
                <input
                  v-if="editingEntryId === entry.id"
                  :id="`qty-input-${entry.id}`"
                  type="number"
                  v-model="editingQuantity"
                  @blur="saveQuantity(entry)"
                  @keyup.enter="saveQuantity(entry)"
                  @keyup.esc="editingEntryId = null; editingQuantity = null;"
                  class="qty-input"
                />
                <span v-else @click="editQuantity(entry)" class="qty-display">
                  {{ entry.quantity }}
                </span>
              </div>
              <div class="col-food">
                <span @click="openFoodEditor(entry)" class="food-name-clickable">{{ entry.food }}</span>
              </div>
              <div class="col-cals">{{ entry.total_calories || 0 }}</div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-log-message">
        <p>No meals logged for today. Start by recording what you ate!</p>
      </div>
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
.transcription-controls button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
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
.ai-response-container {
  margin-top: 20px;
  padding: 15px;
  border: 1px solid #2ecc71;
  background-color: #f0fff4;
  border-radius: 8px;
  text-align: left;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.confirmation-buttons {
  margin-top: 15px;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.confirmation-buttons button {
  border: none;
  border-radius: 5px;
}

.confirmation-buttons button:first-of-type:not(:last-of-type) {
  background-color: #2ecc71;
  color: white;
}
.confirmation-buttons .cancel-button {
  background-color: #e74c3c;
  color: white;
}
.daily-log-container {
  max-width: 600px;
  margin: 40px auto;
  text-align: left;
}

.date-navigation {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.date-header {
  font-size: 1.2em;
  color: #333;
  margin: 0;
}

.nav-button {
  background: none;
  border: 1px solid #ccc;
  border-radius: 50%;
  width: 30px;
  height: 30px;
  cursor: pointer;
}

.daily-total {
  text-align: center;
  font-size: 1.5em;
  margin-bottom: 20px;
  color: #2c3e50;
}

.meal-swimlanes {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.meal-lane {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  background-color: #fff;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.meal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 15px;
  background-color: #f8f9fa;
  font-size: 1.1em;
  text-transform: capitalize;
  border-bottom: 1px solid #e0e0e0;
}

.meal-total {
  font-weight: normal;
  font-size: 0.9em;
  color: #555;
}

.entry-row {
  display: grid;
  grid-template-columns: 50px 1fr 80px;
  gap: 10px;
  padding: 8px 15px;
  align-items: center;
}

.entry-row:not(:last-child) {
  border-bottom: 1px solid #f1f3f5;
}

.header-row {
  font-weight: bold;
  color: #333;
  padding-top: 12px;
  padding-bottom: 12px;
}

.col-qty { text-align: center; }
.qty-display {
  display: inline-block;
  padding: 5px;
  border-radius: 4px;
  background-color: #eaf2f8;
  cursor: pointer;
  min-width: 30px;
}
.qty-input {
  width: 50px;
  padding: 4px;
  text-align: center;
  border: 1px solid #3498db;
  border-radius: 4px;
  background-color: #fdfefe;
}
/* Hide the number input spinners for a cleaner look */
.qty-input::-webkit-outer-spin-button,
.qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.qty-input[type=number] { -moz-appearance: textfield; }
.col-food { background-color: #e8f6f3; padding: 5px; border-radius: 4px; }
.food-name-clickable {
  cursor: pointer;
  text-decoration: underline dotted;
}
.col-cals { background-color: #fdedec; padding: 5px; border-radius: 4px; text-align: right; }
.support-error {
  color: #c0392b;
}
.empty-log-message {
  text-align: center;
  padding: 20px;
  background-color: #f8f9fa;
  border-radius: 8px;
  color: #6c757d;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  padding: 20px 30px;
  border-radius: 8px;
  width: 90%;
  max-width: 400px;
  box-shadow: 0 5px 15px rgba(0,0,0,0.3);
}

.modal-content h3 {
  margin-top: 0;
}

.food-name-display {
  font-size: 1.2em;
  font-weight: bold;
  text-transform: capitalize;
  margin-bottom: 20px;
}

.modal-form-group {
  margin-bottom: 20px;
}

.modal-form-group label {
  display: block;
  margin-bottom: 5px;
}

.modal-form-group input {
  width: 100%;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
