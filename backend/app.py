from flask import Flask, jsonify, request
from flask_cors import CORS

# instantiate the app
app = Flask(__name__)

# enable CORS
# This will allow the Vue.js frontend to make requests to the backend.
CORS(app, resources={r'/api/*': {'origins': '*'}})


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
    print(f"Received prompt: {prompt_text}")

    # This is where you will eventually call the Gemini API.
    # For now, we'll just confirm receipt of the text.
    return jsonify({'status': 'success', 'received_text': prompt_text})

if __name__ == '__main__':
    app.run(debug=True)
