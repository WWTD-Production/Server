import os
import random
import string
import traceback
import json
import io
import uuid
import datetime

from flask import Flask, request, abort, jsonify, url_for, current_app
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore, storage
from openai import OpenAI
import stripe

# Initialize Firebase Admin SDK
cred = credentials.Certificate('wwtd-service-account.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
stripe.api_key = os.environ.get("STRIPE_API_KEY")

    
app = Flask(__name__)
CORS(app)


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    user_id = request.json.get('user_id')  # Get user ID from the client
    subscription_type = request.json.get('subscription_type')
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Subscription',
                    },
                    'unit_amount': 199 if request.json.get('subscription_type') == 'monthly' else 999,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://wwtd.webflow.io/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://wwtd.webflow.io/subscribe',
            metadata={
                'subscription_type': subscription_type,
                'user_id': request.json.get('user_id')
            }
        )
        return jsonify({'id': session.id, 'url': session.url})
    except Exception as e:
        current_app.logger.error("Failed to create checkout session:", exc_info=True)
        return jsonify({'error': str(e)}), 403
        

@app.route('/webhook', methods=['POST'])
def webhook_received():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_eUqWH6pvzcBHyYfmfJM2KmADtogxdeht'

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
        # Handle the checkout.session.completed event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            handle_checkout_session(session)
            user_id = session.metadata['user_id']
        return 'Success', 200
    except Exception as e:
        return str(e), 400

def handle_checkout_session(session):
    # Retrieve metadata from session
    subscription_type = session.get('metadata', {}).get('subscription_type')
    user_id = session.get('metadata', {}).get('user_id')
    
    # Determine the expiration date based on the subscription type
    expiration_date = datetime.datetime.utcnow()
    if subscription_type == 'monthly':
        expiration_date += datetime.timedelta(days=30)
    elif subscription_type == 'yearly':
        expiration_date += datetime.timedelta(days=365)

    # Update the user's subscription status in Firestore
    user_ref = db.collection('users').document(user_id)
    user_ref.update({
        'subscriptionExpirationDate': expiration_date,
        'isSubscribed' : True,
        'subscriptionPlan' : subscription_type
    })
    
    print(f"Subscription for user {user_id} updated to expire on {expiration_date}")





@app.route('/start_conversation', methods=['POST'])
def start_conversation():
    data = request.json
    preview_message = data['preview_message']
    model = data['model']
    user_id = data['user_id']
    thread_id = generate_random_id()

    # Define the new thread with required properties
    new_thread = {
        'id': thread_id,
        'dateCreated': datetime.datetime.now(datetime.timezone.utc),
        'previewMessage': preview_message,
        'model': model,
        'status': 'active'
    }

    thread_ref = db.collection('users').document(user_id).collection('messageThreads').document(thread_id)
    thread_ref.set(new_thread)

    return jsonify({"thread_id": thread_id}), 200
    
    
@app.route('/send_query', methods=['POST'])
def send_query():
    data = request.json
    user_message = data['message']
    user_id = data['user_id']
    thread_id = data['thread_id']

    # Retrieve user data to check subscription status and token count
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    is_subscribed = user_data.get('isSubscribed', False)
    available_tokens = user_data.get('availableTokens', 0)
        
    # Message for OpenAI API
    system_message_openai = {
        "role": "system",
        "content": "You are a Christian assistant providing helpful advice based on the teachings of Jesus Christ. Quote scripture whenever applicable and provide concise answers."
    }
    user_message_openai = {
        "role": "user",
        "content": user_message
    }

    # Data to store in Firestore
    user_message_firestore = {
        "id": generate_random_id(),
        "role": "user",
        "content": user_message,
        "timestamp": firestore.SERVER_TIMESTAMP
    }

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[system_message_openai, user_message_openai]
        )
        tokens_used = response.usage.total_tokens

        if response.choices:
            assistant_message_content = response.choices[0].message.content
        else:
            assistant_message_content = "No response received"
            
        assistant_message_firestore = {
            "id": generate_random_id(),
            "role": "assistant",
            "content": assistant_message_content,
            "timestamp": firestore.SERVER_TIMESTAMP
        }

        # Store both messages in Firestore under the specified thread ID
        messages_ref = db.collection('users').document(user_id).collection('messageThreads').document(thread_id).collection('messages')
        messages_ref.add(user_message_firestore)
        messages_ref.add(assistant_message_firestore)

        if not is_subscribed:
            decrement_user_tokens(user_ref, tokens_used)
            
        return jsonify({"response": assistant_message_content}), 200
    except Exception as e:
        current_app.logger.error("An error occurred while processing the OpenAI API request.", exc_info=True)
        return jsonify({"error": str(e)}), 500

def generate_random_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


def decrement_user_tokens(user_ref, tokens_used):
    try:
        user_ref.update({'availableTokens': firestore.Increment(-tokens_used)})
    except Exception as e:
        print(f"Failed to update tokens for user: {e}")




@app.route("/")
def base():
    logo_url = url_for('static', filename='wwjd-logo.png')
    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Service Status</title>
        <style>
            body, html {{
                height: 100%;
                margin: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                flex-direction: column;
                font-family: Arial, sans-serif;
                background-color: #e8d7bc; /* Set the background color */
                color: #8A8885; /* Set text color to white */

            }}
            .content {{
                text-align: center;
            }}
            .logo {{
                width: 600px;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="content">
            <img src="{logo_url}" alt="Logo" class="logo">
            <h1>All Systems Operational</h1>
        </div>
    </body>
    </html>
    '''
    
    
if __name__ == '__main__':
    app.run(debug=True)
