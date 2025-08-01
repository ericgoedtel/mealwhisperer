from flask import Flask, jsonify
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

if __name__ == '__main__':
    app.run(debug=True)

