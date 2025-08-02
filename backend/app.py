import os
from flask import Flask, jsonify, request
import re
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


@app.route('/api/prompt', methods=['POST'])
def handle_prompt():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    prompt_text = data['text'].strip()
    print(f"Received prompt: '{prompt_text}'")

    system_instruction = """
    You are a meal logging assistant. Your primary function is to identify when a user wants to log a meal.
    If the user's request is to log a food item for a specific meal (e.g., "log eggs for breakfast", "add a sandwich to my lunch"), respond ONLY with a JSON object in the following format:
    {"action": "log_meal", "details": {"food": "...", "meal": "..."}}

    Do not add any other text, explanation, or markdown formatting around the JSON.

    If the user's request is anything else (e.g., a question, a greeting, a general command), respond naturally as a helpful assistant.
    """
    try:
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=system_instruction
        )
        response = model.generate_content(prompt_text)

        # Attempt to parse the response as JSON to detect the structured command
        try:
            response_data = json.loads(response.text)
            if response_data.get('action') == 'log_meal':
                details = response_data.get('details', {})
                food = details.get('food', 'unknown')
                meal = details.get('meal', 'unknown')
                print(f"Gemini identified command: Logging '{food}' for '{meal}'.")
                response_text = f"Okay, I've logged '{food}' for {meal}."
                return jsonify({
                    'status': 'success',
                    'action': 'log_meal',
                    'details': {'food': food, 'meal': meal},
                    'response_text': response_text
                })
        except (json.JSONDecodeError, AttributeError):
            # If it's not our specific JSON, treat it as a standard text response
            print(f"Gemini response: '{response.text}'")
            return jsonify({'status': 'success', 'action': 'ai_response', 'response_text': response.text})

    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while processing your request.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
