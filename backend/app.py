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


def perform_readback_or_confirmation(details):
    """Checks quantity and returns the appropriate readback/confirmation action."""
    food = details.get('food', 'unknown')
    meal = details.get('meal', 'unknown')
    quantity = details.get('quantity', 1)
    per_item_calories = details.get('calories')

    calorie_text = ""
    if per_item_calories is not None:
        try:
            # Calculate total calories and add it to the details for the final log
            total_calories = int(per_item_calories) * int(quantity)
            details['total_calories'] = total_calories
            calorie_text = f", which is about {total_calories} calories"
        except (ValueError, TypeError):
            # If calories or quantity aren't valid numbers, just skip the text
            calorie_text = ""

    # --- SANITY CHECK & READBACK ---
    if quantity > 6:
        # For high quantities, the readback is a direct question and requires explicit confirmation.
        print(f"High quantity ({quantity}) detected. Requiring explicit confirmation.")
        return jsonify({
            'status': 'success',
            'action': 'explicit_confirmation_required',
            'details': details,
            'response_text': f"Did you really have {quantity} {food}{calorie_text}? Please confirm to log."
        })
    else:
        # For normal quantities, do the standard readback with auto-confirmation.
        print(f"Readback required for: {details}")
        return jsonify({
            'status': 'success',
            'action': 'readback_required',
            'details': details,
            'response_text': f"Got it: {quantity} {food} for {meal}{calorie_text}. I'll log this in a moment unless you cancel."
        })

def handle_confirmed_log(data):
    """Handles a request that has been confirmed by the user (or by timeout)."""
    details = data.get('details', {})
    food = details.get('food', 'unknown')
    meal = details.get('meal', 'unknown')
    quantity = details.get('quantity', 1)
    total_calories = details.get('total_calories') # Get the pre-calculated total

    calorie_text = ""
    if total_calories is not None:
        calorie_text = f" for a total of {total_calories} calories"

    # This is where you would persist the data to a database.
    print(f"CONFIRMED: Logging {quantity} '{food}' for '{meal}'{calorie_text}.")

    return jsonify({
        'status': 'success',
        'action': 'log_finalized',
        'response_text': f"Done. I've logged {quantity} {food} for {meal}{calorie_text}."
    })

def handle_initial_prompt(data):
    """Handles the initial text prompt from the user by calling the AI."""
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    prompt_text = data['text'].strip()

    system_instruction = """
    You are a meal logging assistant. Your primary function is to identify when a user wants to log a meal.
    If the user's request is to log a food item for a specific meal (e.g., "log eggs for breakfast", "I ate 2 sandwiches for lunch"), respond ONLY with a JSON object in the following format:
    {"action": "log_meal", "details": {"food": "...", "meal": "...", "quantity": ..., "calories": ...}}

    Also, estimate the calories for a SINGLE UNIT of the food item and include it in the "calories" field as a number. For example, for "2 eggs", provide the calories for one egg.

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
                meal = details.get('meal') # Use default None to correctly trigger the check below
                quantity = details.get('quantity')
                if quantity is None:
                    quantity = 1
                
                details['quantity'] = quantity

                # --- MEAL CHECK ---
                if not meal:
                    print(f"Meal is missing for food '{food}'. Asking for clarification.")
                    return jsonify({
                        'status': 'success',
                        'action': 'meal_clarification_required',
                        'details': details,
                        'response_text': f"Which meal was the {food} for? (e.g., breakfast, lunch, dinner, snack)"
                    })
                
                # If meal is present, proceed to readback/confirmation
                return perform_readback_or_confirmation(details)

        except (json.JSONDecodeError, AttributeError):
            # If it's not our specific JSON, treat it as a standard text response
            print(f"Gemini response: '{response.text}'")
            return jsonify({'status': 'success', 'action': 'ai_response', 'response_text': response.text})
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while processing your request.'}), 500

def handle_meal_clarification(data):
    """Handles the user's response to a meal clarification prompt."""
    details = data.get('details')
    meal_clarification = data.get('meal', '').lower().strip()
    valid_meals = ["breakfast", "lunch", "dinner", "snack"]

    if meal_clarification not in valid_meals:
        print(f"Invalid meal clarification: '{meal_clarification}'. Cancelling log.")
        return jsonify({
            'status': 'error',
            'action': 'log_cancelled',
            'response_text': f"'{meal_clarification}' is not a valid meal. Please try logging again."
        })

    print(f"Meal clarified to '{meal_clarification}'.")
    details['meal'] = meal_clarification
    # The meal is now clarified, proceed to the next step
    return perform_readback_or_confirmation(details)

@app.route('/api/prompt', methods=['POST'])
def handle_prompt():
    """Main route to handle all prompt-related requests."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Route to the correct handler based on the request payload
    if 'text' in data:
        prompt_text = data.get('text')
        print(f"Received initial prompt: '{prompt_text.strip()}'")
        return handle_initial_prompt(data)

    if data.get('action') == 'confirm_log' and 'details' in data:
        print("Received confirmation to log.")
        return handle_confirmed_log(data)

    if data.get('action') == 'clarify_meal' and 'details' in data and 'meal' in data:
        print("Received meal clarification.")
        return handle_meal_clarification(data)

    return jsonify({'error': 'Invalid request payload'}), 400

if __name__ == '__main__':
    app.run(debug=True)
