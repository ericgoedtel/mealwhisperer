import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import json
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# instantiate the app
app = Flask(__name__)

# enable CORS
# This will allow the Vue.js frontend to make requests to the backend.
CORS(app, resources={r'/api/*': {'origins': '*'}})

# Configure the Gemini API
try:
    api_key = os.environ["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except KeyError:
    print("CRITICAL: GOOGLE_API_KEY environment variable not set. The service will not work.")


def handle_confirmed_log(data):
    """Handles a request that has been confirmed by the user (or by timeout)."""
    details = data.get('details', {})
    food = details.get('food', 'unknown')
    meal = details.get('meal', 'unknown')
    quantity = details.get('quantity', 1)

    # This is where you would persist the data to a database.
    print(f"CONFIRMED: Logging {quantity} '{food}' for '{meal}'.")

    return jsonify({
        'status': 'success',
        'action': 'log_finalized',
        'response_text': f"Done. I've logged {quantity} {food} for {meal}."
    })

def handle_initial_prompt(data):
    """Handles the initial text prompt from the user by calling the AI."""
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    prompt_text = data['text'].strip()

    system_instruction = """
    You are a meal logging assistant. Your primary function is to identify when a user wants to log a meal.
    If the user's request is to log a food item for a specific meal (e.g., "log eggs for breakfast", "I ate 2 sandwiches for lunch"), respond ONLY with a JSON object in the following format:
    {"action": "log_meal", "details": {"food": "...", "meal": "...", "quantity": ...}}

    The "quantity" is the number describing how many of the food item were eaten. It is usually found right before the food name.
    If multiple numbers are present, use context to determine the correct quantity. For example, in 'I ate 2 large pizzas on my 30th birthday', the quantity is 2, not 30.
    If the quantity is ambiguous or seems like a transcription error (e.g., '5 817 eggs'), choose the most plausible number that modifies the food item.
    If no quantity is mentioned, you can omit the field as the system will default to 1.

    Your response for a log_meal action MUST be ONLY the raw JSON object itself, with no surrounding text, explanation, or markdown code fences (like ```json).

    If the user's request is anything else (e.g., a question, a greeting, a general command), respond conversationally as a helpful assistant.
    """
    try:
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=system_instruction
        )
        response = model.generate_content(prompt_text)

        # Attempt to parse the response as JSON to detect the structured command
        try:
            raw_text = response.text
            # Clean potential markdown fences from the response
            if raw_text.strip().startswith("```json"):
                # Strips ```json from the start and ``` from the end
                cleaned_text = raw_text.strip()[7:-3].strip()
            else:
                cleaned_text = raw_text.strip()

            response_data = json.loads(cleaned_text)
            if response_data.get('action') == 'log_meal':
                details = response_data.get('details', {})
                food = details.get('food', 'unknown')
                meal = details.get('meal', 'unknown')
                quantity = details.get('quantity')
                if quantity is None:
                    quantity = 1
                
                details['quantity'] = quantity

                # --- SANITY CHECK & READBACK ---
                if quantity > 6:
                    # For high quantities, the readback is a direct question and requires explicit confirmation.
                    print(f"High quantity ({quantity}) detected. Requiring explicit confirmation.")
                    return jsonify({
                        'status': 'success',
                        'action': 'explicit_confirmation_required',
                        'details': details,
                        'response_text': f"Did you really have {quantity} {food}? Please confirm to log."
                    })
                else:
                    # For normal quantities, do the standard readback with auto-confirmation.
                    print(f"Readback required for: {details}")
                    return jsonify({
                        'status': 'success',
                        'action': 'readback_required',
                        'details': details,
                        'response_text': f"Got it: {quantity} {food} for {meal}. I'll log this in a moment unless you cancel."
                    })

        except (json.JSONDecodeError, AttributeError):
            # If it's not our specific JSON, treat it as a standard text response
            print(f"Gemini response: '{response.text}'")
            return jsonify({'status': 'success', 'action': 'ai_response', 'response_text': response.text})
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while processing your request.'}), 500

@app.route('/api/prompt', methods=['POST'])
def handle_prompt():
    """Main route to handle all prompt-related requests."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    prompt_text = data.get('text')
    if prompt_text is not None:
        print(f"Received initial prompt: '{prompt_text.strip()}'")
        return handle_initial_prompt(data)

    if data.get('action') == 'confirm_log' and 'details' in data:
        print("Received confirmation to log.")
        return handle_confirmed_log(data)

    return jsonify({'error': 'Invalid request payload'}), 400

if __name__ == '__main__':
    app.run(debug=True)
