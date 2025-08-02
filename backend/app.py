# pylint: disable=C0301

"""
This module provides a Flask API for a meal logging application.
It interfaces with the Google Gemini AI to process natural language prompts,
and persists meal data in a local SQLite database.
"""
"""
This module interfaces a human with a generative AI for the purposes
of logging nutrition and meals.
"""

import json
import os
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
import google.generativeai as genai
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

DB_FILE = 'meals.db'

LATEST_SCHEMA_VERSION = 4
# Read model name from environment variable with a sensible default
GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-1.5-flash')

def _run_migration_v2(cursor):
    """
    Migration v2:
    1. Renames 'timestamp' to 'log_timestamp' for clarity.
    2. Adds the 'meal_date' column to store when the meal was eaten.
    """
    try:
        cursor.execute("PRAGMA table_info(meal_logs)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'timestamp' in columns and 'log_timestamp' not in columns:
            cursor.execute("ALTER TABLE meal_logs RENAME COLUMN timestamp TO log_timestamp")
            print("Migration v2: Renamed 'timestamp' to 'log_timestamp'.")

        if 'meal_date' not in columns:
            cursor.execute("ALTER TABLE meal_logs ADD COLUMN meal_date DATE")
            print("Migration v2: Added 'meal_date' column.")
            cursor.execute("UPDATE meal_logs SET meal_date = date(log_timestamp) WHERE meal_date IS NULL")
            print("Migration v2: Backfilled 'meal_date' for existing rows.")

    except sqlite3.Error as e:
        print(f"Error applying migration v2: {e}")
        raise # Re-raise to ensure the transaction is rolled back

def _run_migration_v3(cursor):
    """
    Migration v3:
    1. Changes 'log_timestamp' from DATETIME string to INTEGER (Unix epoch).
    """
    try:
        # The 'rebuild table' approach is the safest way to change column types and defaults in SQLite
        cursor.execute('''
            CREATE TABLE meal_logs_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_timestamp INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                meal_date DATE NOT NULL,
                food TEXT NOT NULL,
                meal TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_calories INTEGER
            )
        ''')
        print("Migration v3: Created new temporary table.")

        # Copy data, converting the timestamp
        cursor.execute('''
            INSERT INTO meal_logs_new (id, log_timestamp, meal_date, food, meal, quantity, total_calories)
            SELECT id, strftime('%s', log_timestamp), meal_date, food, meal, quantity, total_calories
            FROM meal_logs
        ''')
        print("Migration v3: Migrated data to new table.")

        cursor.execute("DROP TABLE meal_logs")
        print("Migration v3: Dropped old table.")

        cursor.execute("ALTER TABLE meal_logs_new RENAME TO meal_logs")
        print("Migration v3: Renamed new table.")
    except sqlite3.Error as e:
        print(f"Error applying migration v3: {e}")
        raise

def _run_migration_v4(cursor):
    """
    Migration v4:
    1. Creates a canonical 'foods' table for items and their calories.
    2. Rebuilds 'meal_logs' to use a foreign key 'food_id'.
    """
    try:
        # Create the new foods table with a unique constraint on the name
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                calories INTEGER NOT NULL
            )
        ''')
        print("Migration v4: Created 'foods' table.")

        # Rebuild meal_logs table to reference the new foods table.
        # This approach is safe for an empty database as per the user's context.
        cursor.execute("PRAGMA foreign_keys=off")
        cursor.execute("BEGIN TRANSACTION")

        cursor.execute('''
            CREATE TABLE meal_logs_v4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_timestamp INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                meal_date DATE NOT NULL,
                food_id INTEGER NOT NULL,
                meal TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_calories INTEGER,
                FOREIGN KEY (food_id) REFERENCES foods (id)
            )
        ''')
        cursor.execute("DROP TABLE meal_logs")
        cursor.execute("ALTER TABLE meal_logs_v4 RENAME TO meal_logs")
        cursor.execute("COMMIT")
        cursor.execute("PRAGMA foreign_keys=on")
        print("Migration v4: Rebuilt 'meal_logs' table with 'food_id' foreign key.")
    except sqlite3.Error as e:
        print(f"Error applying migration v4: {e}")
        cursor.execute("ROLLBACK")
        raise

def init_db():
    """Initializes and migrates the database to the latest version."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Get current schema version using SQLite's built-in pragma
        cursor.execute("PRAGMA user_version")
        current_version = cursor.fetchone()[0]
        print(f"Database version: {current_version}")

        if current_version < 1:
            print("Applying schema v1 (initial setup)...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS meal_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    food TEXT NOT NULL,
                    meal TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    total_calories INTEGER
                )
            ''')
            cursor.execute("PRAGMA user_version = 1")
            current_version = 1
            print("Schema v1 applied.")

        if current_version < 2:
            print("Applying schema v2...")
            _run_migration_v2(cursor)
            cursor.execute("PRAGMA user_version = 2")
            print("Schema v2 applied.")

        if current_version < 3:
            print("Applying schema v3...")
            _run_migration_v3(cursor)
            cursor.execute("PRAGMA user_version = 3")
            print("Schema v3 applied.")

        if current_version < 4:
            print("Applying schema v4...")
            _run_migration_v4(cursor)
            cursor.execute("PRAGMA user_version = 4")
            print("Schema v4 applied.")

        if current_version == LATEST_SCHEMA_VERSION:
            print("Database is up to date.")

        conn.commit()
    except sqlite3.Error as e:
        print(f"DATABASE MIGRATION ERROR: {e}")
        conn.rollback()
    finally:
        conn.close()

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

SYSTEM_INSTRUCTION = """
You are a meal logging assistant. Your primary function is to identify when a user wants to log a meal.

If the user's request is to log a food item, respond ONLY with a JSON object in the following format:
{"action": "log_meal", "details": {"food": "...", "meal": "...", "quantity": ..., "calories": ..., "date_keyword": "..."}}

From the user's prompt, extract a date reference keyword.
- If the user says "today" or does not mention a date, set "date_keyword" to "today".
- If the user says "yesterday", set "date_keyword" to "yesterday".
- If the user mentions any other date phrase (e.g., "last Tuesday", "October 27th"), set "date_keyword" to that exact phrase (e.g., "last Tuesday").

Do NOT calculate the final date yourself. Just return the keyword or phrase.

The "meal" field MUST be one of "breakfast", "lunch", "dinner", or "snack". If the user does not specify a valid meal, set the "meal" field to null. Do not guess a meal or use values like "other".

Also, estimate the calories for a SINGLE UNIT of the food item and include it in the "calories" field as a number. For example, for "2 eggs", provide the calories for one egg.

The "quantity" is the number describing how many of the food item were eaten. It is usually found right before the food name.
If multiple numbers are present, use context to determine the correct quantity. For example, in 'I ate 2 large pizzas on my 30th birthday', the quantity is 2, not 30.
If the quantity is ambiguous or seems like a transcription error (e.g., '5 817 eggs'), choose the most plausible number that modifies the food item.
If no quantity is mentioned, you can omit the field as the system will default to 1.

Your response for a log_meal action MUST be ONLY the raw JSON object itself, with no surrounding text, explanation, or markdown code fences (like ```json).

If the user's request is anything else (e.g., a question, a greeting, a general command), respond conversationally as a helpful assistant.
"""

@app.route('/api/logs/<string:meal_date>', methods=['GET'])
def get_logs_for_date(meal_date):
    """Retrieves and groups all meal logs for a specific date."""
    try:
        # Validate that the provided string is a valid date in YYYY-MM-DD format
        date.fromisoformat(meal_date)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    try:
        conn = sqlite3.connect(DB_FILE)
        # Make the connection return rows that can be accessed by column name
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                ml.id,
                f.id as food_id,
                ml.meal,
                ml.quantity,
                ml.total_calories,
                f.name as food,
                f.calories as per_item_calories
            FROM meal_logs ml
            JOIN foods f ON ml.food_id = f.id
            WHERE ml.meal_date = ?
            ORDER BY ml.log_timestamp
            """,
            (meal_date,)
        )
        rows = cursor.fetchall()
        conn.close()

        # Process the rows into a structured dictionary
        meals_data = defaultdict(lambda: {'entries': [], 'total_meal_calories': 0})
        total_daily_calories = 0

        for row in rows:
            meal_type = row['meal']
            # Use the historically stored total_calories for accuracy
            historical_total_calories = row['total_calories'] or 0

            meals_data[meal_type]['entries'].append(dict(row))
            meals_data[meal_type]['total_meal_calories'] += historical_total_calories
            total_daily_calories += historical_total_calories

        return jsonify({
            'total_daily_calories': total_daily_calories,
            'meals': dict(meals_data) # Convert defaultdict to a regular dict for JSON
        })

    except sqlite3.Error as e:
        print(f"DATABASE ERROR on SELECT: {e}")
        return jsonify({'error': 'Could not retrieve meal logs.'}), 500

def perform_readback_or_confirmation(details):
    """Checks quantity and returns the appropriate readback/confirmation action."""
    food = details.get('food', 'unknown')
    meal = details.get('meal', 'unknown')
    quantity = details.get('quantity', 1)
    meal_date_str = details.get('meal_date')
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

    date_text = ""
    if meal_date_str:
        try:
            meal_date_obj = date.fromisoformat(meal_date_str)
            today = date.today()
            yesterday = today - timedelta(days=1)

            if meal_date_obj == today:
                date_text = "" # Default, no extra text
            elif meal_date_obj == yesterday:
                date_text = " yesterday"
            else:
                date_text = f" on {meal_date_obj.strftime('%A, %B %d')}"
        except (ValueError, TypeError):
            date_text = "" # If date is malformed, just ignore it

    # --- SANITY CHECK & READBACK ---
    if quantity > 6:
        # For high quantities, the readback is a direct question and requires explicit confirmation.
        print(f"High quantity ({quantity}) detected. Requiring explicit confirmation.")
        return jsonify({
            'status': 'success',
            'action': 'explicit_confirmation_required',
            'details': details,
            'response_text': f"Did you really have {quantity} {food}{date_text}{calorie_text}? Please confirm to log."
        })
    # For normal quantities, do the standard readback with auto-confirmation.
    print(f"Readback required for: {details}")
    return jsonify({
        'status': 'success',
        'action': 'readback_required',
        'details': details,
        'response_text': f"Got it: {quantity} {food} for {meal}{date_text}{calorie_text}. I'll log this in a moment unless you cancel."
    })

def handle_confirmed_log(data):
    """Handles a request that has been confirmed by the user (or by timeout)."""
    details = data.get('details', {})
    food = details.get('food', 'unknown')
    meal = details.get('meal', 'unknown')
    quantity = details.get('quantity', 1)
    meal_date = details.get('meal_date') # This will be a string 'YYYY-MM-DD'
    total_calories = details.get('total_calories') # Get the pre-calculated total

    calorie_text = ""
    if total_calories is not None:
        calorie_text = f" for a total of {total_calories} calories"

    # --- Persist data to the database ---
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO meal_logs (meal_date, food_id, meal, quantity, total_calories) VALUES (?, ?, ?, ?, ?)",
            (meal_date, details.get('food_id'), meal, quantity, total_calories)
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"DATABASE ERROR on INSERT: {e}")
        # We can still return a success response to the user even if DB write fails

    print(f"CONFIRMED: Logging {quantity} '{food}' for '{meal}'{calorie_text}.")

    return jsonify({
        'status': 'success',
        'action': 'log_finalized',
        'response_text': f"Done. I've logged {quantity} {food} for {meal}{calorie_text}."
    })

def resolve_meal_date(date_keyword: str) -> str:
    """
    Resolves a date keyword from the LLM into a YYYY-MM-DD string.
    This function is the single source of truth for date calculations.
    """
    today = date.today()
    if not date_keyword or date_keyword.lower() == 'today':
        return today.isoformat()
    if date_keyword.lower() == 'yesterday':
        return (today - timedelta(days=1)).isoformat()

    # Placeholder for a future, more advanced natural language date parser for phrases like "last Tuesday"
    # For now, if we don't recognize the keyword, we default to today.
    print(f"Unrecognized date_keyword: '{date_keyword}'. Defaulting to today.")
    return today.isoformat()

def get_or_create_food(food_name, llm_calories):
    """Finds a food by name or creates it if it doesn't exist. Returns (food_id, canonical_calories)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, calories FROM foods WHERE name = ?", (food_name,))
    food_row = cursor.fetchone()

    if food_row:
        food_id, canonical_calories = food_row[0], food_row[1]
        print(f"Found existing food '{food_name}' (ID: {food_id}) with {canonical_calories} calories.")
    else:
        try:
            calories_to_insert = int(llm_calories) if llm_calories is not None else 0
        except (ValueError, TypeError):
            calories_to_insert = 0 # Default to 0 if LLM gives non-numeric calorie value

        cursor.execute("INSERT INTO foods (name, calories) VALUES (?, ?)", (food_name, calories_to_insert))
        food_id = cursor.lastrowid
        canonical_calories = calories_to_insert
        print(f"Created new food '{food_name}' (ID: {food_id}) with {canonical_calories} calories.")

    conn.commit()
    conn.close()
    return food_id, canonical_calories

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

def _call_llm_and_parse_json(prompt_text, system_instruction):
    """
    Calls the Gemini API and parses the JSON response.
    Returns a tuple: (parsed_data, is_actionable_json).
    Raises exceptions for API or parsing failures.
    """
    model = genai.GenerativeModel(GEMINI_MODEL_NAME, system_instruction=system_instruction)
    response = model.generate_content(prompt_text)

    raw_text = response.text
    if raw_text.strip().startswith("```json"):
        cleaned_text = raw_text.strip()[7:-3].strip()
    else:
        cleaned_text = raw_text.strip()

    try:
        response_data = json.loads(cleaned_text)
        is_actionable = response_data.get('action') == 'log_meal'
        return response_data, is_actionable
    except (json.JSONDecodeError, AttributeError):
        # Not valid JSON or doesn't have the expected structure, treat as conversational.
        return raw_text, False

def handle_initial_prompt(data):
    """Handles the initial text prompt from the user by calling the AI."""
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    prompt_text = data['text'].strip()

    try:
        response_data, is_actionable = _call_llm_and_parse_json(prompt_text, SYSTEM_INSTRUCTION)

        if not is_actionable:
            # The response was conversational text or non-actionable JSON.
            print(f"Gemini response: '{response_data}'")
            return jsonify({'status': 'success', 'action': 'ai_response', 'response_text': str(response_data)})

        # --- Process Actionable Log Request ---
        details = response_data.get('details', {})
        food_name = details.get('food')
        if not food_name:
            return jsonify({'error': 'AI response missing food name.'}), 400

        food_id, canonical_calories = get_or_create_food(food_name, details.get('calories'))
        details.update({
            'food_id': food_id,
            'calories': canonical_calories,
            'meal_date': resolve_meal_date(details.get('date_keyword')),
            'quantity': details.get('quantity') or 1
        })

        # --- Meal Type Validation ---
        meal = details.get('meal')
        valid_meals = ["breakfast", "lunch", "dinner", "snack"]
        if not meal or str(meal).lower().strip() not in valid_meals:
            print(f"Meal is missing or invalid ('{meal}') for food '{food_name}'. Asking for clarification.")
            return jsonify({
                'status': 'success',
                'action': 'meal_clarification_required',
                'details': details,
                'response_text': f"Which meal was the {food_name} for? (e.g., breakfast, lunch, dinner, snack)"
            })

        return perform_readback_or_confirmation(details)

    except sqlite3.Error as e:
        print(f"DATABASE ERROR during initial prompt: {e}")
        return jsonify({'error': 'A database error occurred.'}), 500
    except Exception as e: # Catch-all for other unexpected errors, including from the API call
        print(f"An unexpected error occurred in handle_initial_prompt: {e}")
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred.'}), 500

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

@app.route('/api/foods/<int:food_id>', methods=['PATCH'])
def update_food_entry(food_id):
    """Updates a canonical food entry's calorie count."""
    data = request.get_json()
    if not data or 'calories' not in data:
        return jsonify({'error': 'Missing calories in request body.'}), 400

    try:
        new_calories = int(data['calories'])
        if not 0 <= new_calories <= 5000: # A reasonable limit for per-item calories
            return jsonify({'error': 'Calories must be between 0 and 5000.'}), 400 # pylint: disable=R1705
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid calories format.'}), 400

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE foods SET calories = ? WHERE id = ?", (new_calories, food_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': f'Food entry {food_id} updated.'})
    except sqlite3.Error as e:
        print(f"DATABASE ERROR on food UPDATE: {e}")
        return jsonify({'error': 'Could not update food entry.'}), 500

def _validate_update_log_request(meal_date, request_data) -> tuple[str | None, int | None]:
    """
    Validates input for updating a log entry.
    Returns a tuple of (error_message, new_quantity).
    """
    try:
        date.fromisoformat(meal_date)
    except (ValueError, TypeError):
        return 'Invalid date format in URL. Use YYYY-MM-DD.', None

    if not request_data or 'quantity' not in request_data:
        return 'Missing quantity in request body.', None

    try:
        new_quantity = int(request_data['quantity'])
        if not 1 <= new_quantity <= 100:
            return 'Quantity must be between 1 and 100.', None
    except (ValueError, TypeError):
        return 'Invalid quantity format.', None

    return None, new_quantity

@app.route('/api/logs/<string:meal_date>/entry/<int:log_id>', methods=['PATCH'])
def update_log_entry(meal_date, log_id):
    """Updates a specific log entry, such as its quantity."""
    data = request.get_json()
    error_message, new_quantity = _validate_update_log_request(meal_date, data)
    if error_message:
        return jsonify({'error': error_message}), 400

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Fetch existing entry to validate and get info
            cursor.execute("SELECT food_id, meal_date FROM meal_logs WHERE id = ?", (log_id,))
            entry = cursor.fetchone()
            if not entry:
                return jsonify({'error': 'Log entry not found.'}), 404
            if entry['meal_date'] != meal_date:
                return jsonify({'error': 'Log entry does not belong to the specified date.'}), 400

            # Fetch canonical calories
            cursor.execute("SELECT calories FROM foods WHERE id = ?", (entry['food_id'],))
            food_row = cursor.fetchone()
            if not food_row:
                return jsonify({'error': 'Associated food item not found, cannot update calories.'}), 500

            per_item_calories = food_row[0]
            new_total_calories = round(per_item_calories * new_quantity)

            # Update the database
            cursor.execute(
                "UPDATE meal_logs SET quantity = ?, total_calories = ? WHERE id = ?",
                (new_quantity, new_total_calories, log_id)
            )
            # The 'with' statement handles the commit on success or rollback on error.

    except sqlite3.Error as e:
        print(f"DATABASE ERROR on UPDATE: {e}")
        return jsonify({'error': 'Could not update log entry.'}), 500

    return jsonify({'status': 'success', 'message': f'Log entry {log_id} updated.'})

@app.route('/api/logs/<string:meal_date>/entry/<int:log_id>', methods=['DELETE'])
def delete_log_entry(meal_date, log_id):
    """Deletes a specific log entry."""
    try:
        # Validate that the provided string is a valid date in YYYY-MM-DD format
        date.fromisoformat(meal_date)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid date format in URL. Use YYYY-MM-DD.'}), 400

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Optional but good practice: Check if the entry exists and belongs to the date before deleting
        cursor.execute("SELECT id FROM meal_logs WHERE id = ? AND meal_date = ?", (log_id, meal_date))
        entry = cursor.fetchone()

        if not entry:
            return jsonify({'error': 'Log entry not found or does not belong to the specified date.'}), 404

        # Delete the entry
        cursor.execute("DELETE FROM meal_logs WHERE id = ?", (log_id,))
        conn.commit()
        return jsonify({'status': 'success', 'message': f'Log entry {log_id} deleted.'})
    except sqlite3.Error as e:
        print(f"DATABASE ERROR on DELETE: {e}")
        return jsonify({'error': 'Could not delete log entry.'}), 500
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
