# app.py
from flask import Flask, render_template

# Create Flask app instance
app = Flask(__name__)

# Define a route for the home page
@app.route('/')
def home():
    return "<h1>Welcome to Flask!</h1><p>This is a basic Flask app.</p>"

# Optional: Add another route
@app.route('/about')
def about():
    return "<h1>About Page</h1><p>This is the about page.</p>"

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
