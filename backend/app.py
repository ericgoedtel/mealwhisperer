import os
from flask import Flask, jsonify, request
from flask_cors import CORS
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


# hello world route
@app.route('/api/hello', methods=['GET'])
def hello_world():
    return jsonify({'message': 'Hello, World from Python!'})

@app.route('/api/prompt', methods=['POST'])
def handle_prompt():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided'}), 400

    prompt_text = data['text']
    print(f"Received prompt: '{prompt_text}'")

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt_text)

        if response.text:
            print(f"Gemini response: '{response.text}'")
            return jsonify({'status': 'success', 'response_text': response.text})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to get a valid response from the AI.'}), 500
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while processing your request.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
