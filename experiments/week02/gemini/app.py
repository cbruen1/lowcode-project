import re
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-goes-here'

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
# Matches anything wrapped in angle brackets, e.g., <script>, <b>, <iframe
HTML_TAG_REGEX = re.compile(r'<[^>]+>')

def validate_contact_form(data):
    errors = {}
    
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    message = data.get('message', '').strip()

    # Validate Name
    if not name:
        errors['name'] = 'Name is required.'
    elif len(name) < 2:
        errors['name'] = 'Name must be at least 2 characters long.'

    # Validate Email
    if not email:
        errors['email'] = 'Email address is required.'
    elif not EMAIL_REGEX.match(email):
        errors['email'] = 'Please enter a valid email address.'

    # Validate Message
    if not message:
        errors['message'] = 'Message is required.'
    elif len(message) < 10:
        errors['message'] = 'Message must be at least 10 characters long.'
    elif HTML_TAG_REGEX.search(message):
        errors['message'] = 'Message cannot contain HTML tags or script elements.'

    return errors

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        form_data = {
            'name': request.form.get('name', ''),
            'email': request.form.get('email', ''),
            'message': request.form.get('message', '')
        }

        errors = validate_contact_form(form_data)

        if errors:
            return render_template('contact.html', errors=errors, form_data=form_data), 400

        flash('Your message has been sent successfully!', 'success')
        return redirect(url_for('contact'))

    return render_template('contact.html', errors={}, form_data={})

if __name__ == '__main__':
    app.run(debug=True)