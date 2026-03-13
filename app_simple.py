from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
import json
from datetime import datetime, timezone, timedelta
import re
import os
from dotenv import load_dotenv
import numpy as np
import hashlib
import random
from functools import wraps
import requests
from typing import Any, Dict, List, Optional
from services.ai_service import AIService
from services.vision_mood_service import VisionMoodService
from services.dataset_recommendation_service import DatasetRecommendationService
from services.flight_api_service import FlightAPIService
from config import Config
from models.db import db
from models.simple_models import (
    FlightSearch,  # keep for search history only
    FlightBooking,
)
try:
    from models.database import (
        User as DbUser,
        Destination as DbDestination,
        Attraction as DbAttraction,
        Festival as DbFestival,
        Review as DbReview,
        VisitedPlace as DbVisitedPlace,
        Booking as DbBooking,
        SecurityLog as DbSecurityLog,
        ChatMessage as DbChatMessage,
        BusTourQueryLog as DbBusTourQueryLog,
        UserMood as DbUserMood,
        QuizAttempt as DbQuizAttempt,
        QuizPoints as DbQuizPoints,
    )
    _DB_MODELS_AVAILABLE = True
except Exception:
    DbUser = DbDestination = DbAttraction = DbFestival = DbReview = None
    DbVisitedPlace = DbBooking = DbSecurityLog = DbChatMessage = None
    DbBusTourQueryLog = DbUserMood = DbQuizAttempt = DbQuizPoints = None
    _DB_MODELS_AVAILABLE = False

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app)
# Configure Gemini API key (set directly from user-supplied key; for production, use environment variables)
app.config['GEMINI_API_KEY'] = 'AIzaSyDy5FrAn3-w3JhMXPUsTJQCpxuZMYHWG90'
# Configure Weather API key (OpenWeatherMap)
app.config['WEATHER_API_KEY'] = 'c289617e1b11167f7304e2978391cb88'
# Configure Flight API key (Aviationstack)
app.config['FLIGHT_API_KEY'] = '4181583e1efeb265b15217c1165cd5a4'
# Configure MySQL via SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize DB and create tables
db.init_app(app)
with app.app_context():
    db.create_all()

# Security functions
def sanitize_input(text):
    """Sanitize user input to prevent XSS and injection attacks"""
    if not text:
        return ""
    # Remove potentially dangerous characters
    text = re.sub(r'[<>"\']', '', str(text))
    return text.strip()

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Password is strong"

def rate_limit_check(user_id, action, limit=10, window=60):
    """Simple rate limiting for API endpoints"""
    current_time = datetime.now()
    if user_id not in user_sessions:
        return True
    
    session_data = user_sessions[user_id]
    if 'rate_limits' not in session_data:
        session_data['rate_limits'] = {}
    
    if action not in session_data['rate_limits']:
        session_data['rate_limits'][action] = []
    
    # Remove old entries
    session_data['rate_limits'][action] = [
        time for time in session_data['rate_limits'][action] 
        if (current_time - time).seconds < window
    ]
    
    # Check if limit exceeded
    if len(session_data['rate_limits'][action]) >= limit:
        return False
    
    # Add current request
    session_data['rate_limits'][action].append(current_time)
    return True

def require_auth(f):
    """Decorator to require authentication for protected endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id or user_id not in users:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

def log_security_event(event_type, user_id=None, details=None):
    """Log security events for monitoring"""
    timestamp = datetime.now().isoformat()
    event = {
        'timestamp': timestamp,
        'event_type': event_type,
        'user_id': user_id,
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', ''),
        'details': details
    }
    # In a real application, this would be logged to a secure database
    print(f"SECURITY EVENT: {json.dumps(event)}")
    # Persist to DB best-effort
    try:
        db_event = DbSecurityLog(
            event_type=event_type,
            user_id=None,
            ip_address=event['ip_address'],
            user_agent=event['user_agent'],
            details=details or {},
        )
        db.session.add(db_event)
        db.session.commit()
    except Exception:
        db.session.rollback()

# Enhanced in-memory storage with mood tracking
users = {}
user_sessions = {}
user_moods = {}  # Store user moods persistently

# Initialize Dataset-Based Recommendation Service with new dataset
print("Initializing Dataset Recommendation Service...")
dataset_service = DatasetRecommendationService("mood_destinations_1000_FULL_UPDATED.csv")
try:
    init_result = dataset_service.initialize()
    print(f"Dataset service initialized: {init_result}")
except Exception as e:
    print(f"Warning: Could not initialize dataset service: {e}")
    import traceback
    traceback.print_exc()
    dataset_service = None

# Initialize Flight API service
flight_api_key = app.config.get('FLIGHT_API_KEY') or os.getenv('FLIGHT_API_KEY')
flight_api_service = FlightAPIService(flight_api_key) if flight_api_key else None

IATA_CITY_MAP = {
    'DEL': 'Delhi', 'BOM': 'Mumbai', 'BLR': 'Bengaluru', 'MAA': 'Chennai', 'HYD': 'Hyderabad',
    'CCU': 'Kolkata', 'NYC': 'New York', 'LAX': 'Los Angeles', 'SFO': 'San Francisco',
    'ORD': 'Chicago', 'LHR': 'London', 'CDG': 'Paris', 'AMS': 'Amsterdam', 'FRA': 'Frankfurt',
    'DXB': 'Dubai', 'DOH': 'Doha', 'SIN': 'Singapore', 'HKG': 'Hong Kong', 'NRT': 'Tokyo',
    'SYD': 'Sydney'
}

# Legacy destinations list - NOW REPLACED BY DATASET
# All destinations now come from mega_destination_dataset.csv via dataset_service
destinations = []  # Empty - dataset service provides all destinations

# Attractions data - NOW REPLACED BY DATASET
# All attractions now come from mega_destination_dataset.csv via dataset_service
attractions = {}  # Empty - dataset service provides all attractions

# Comprehensive Shopping, Souvenirs, Hiking, and Food Data
shopping_places = {}  # Empty - dataset service provides shopping areas
souvenirs = {}  # Empty - dataset service provides data
hiking_adventures = {}  # Empty - dataset service provides hiking places
famous_local_food = {}  # Empty - dataset service provides food data

# Festivals data with upcoming festivals and enhanced details
festivals = {}  # Empty - dataset service provides all festivals

# Quiz questions data with answers and points
quiz_questions = [
    {
        'id': 1,
        'question': 'What type of landscape do you find most calming?',
        'options': ['Mountain peaks', 'Ocean waves', 'Forest greenery', 'Desert sands'],
        'correct_answer': 1,
        'points': 1,
        'category': 'landscape_preference'
    },
    {
        'id': 2,
        'question': 'How do you prefer to spend your evenings while traveling?',
        'options': ['Quiet reading in a cafe', 'Live music and dancing', 'Exploring local markets', 'Relaxing spa treatment'],
        'correct_answer': 2,
        'points': 1,
        'category': 'evening_activities'
    },
    {
        'id': 3,
        'question': 'What motivates you most to visit a new destination?',
        'options': ['Historical significance', 'Natural beauty', 'Cultural experiences', 'Adventure activities'],
        'correct_answer': 3,
        'points': 1,
        'category': 'travel_motivation'
    },
    {
        'id': 4,
        'question': 'How do you prefer to get around in a new city?',
        'options': ['Walking and exploring', 'Public transportation', 'Guided tours', 'Renting a vehicle'],
        'correct_answer': 0,
        'points': 1,
        'category': 'transportation_preference'
    },
    {
        'id': 5,
        'question': 'What type of accommodation appeals to you most?',
        'options': ['Luxury hotel', 'Cozy hostel', 'Local homestay', 'Unique boutique hotel'],
        'correct_answer': 2,
        'points': 1,
        'category': 'accommodation_preference'
    },
    {
        'id': 6,
        'question': 'How do you like to start your day while traveling?',
        'options': ['Early morning workout', 'Leisurely breakfast', 'Sunrise photography', 'Local market visit'],
        'correct_answer': 1,
        'points': 1,
        'category': 'morning_routine'
    },
    {
        'id': 7,
        'question': 'What type of food experience interests you most?',
        'options': ['Fine dining', 'Street food', 'Cooking classes', 'Local specialties'],
        'correct_answer': 3,
        'points': 1,
        'category': 'food_preference'
    },
    {
        'id': 8,
        'question': 'How do you prefer to interact with locals?',
        'options': ['Learn their language', 'Share stories over meals', 'Participate in activities', 'Observe and learn'],
        'correct_answer': 2,
        'points': 1,
        'category': 'local_interaction'
    },
    {
        'id': 9,
        'question': 'What type of souvenir do you like to bring back?',
        'options': ['Local crafts', 'Photographs', 'Experiences and memories', 'Traditional clothing'],
        'correct_answer': 2,
        'points': 1,
        'category': 'souvenir_preference'
    },
    {
        'id': 10,
        'question': 'How do you prefer to plan your travel itinerary?',
        'options': ['Detailed schedule', 'Flexible planning', 'Local recommendations', 'Spontaneous decisions'],
        'correct_answer': 1,
        'points': 1,
        'category': 'planning_style'
    }
]

# User quiz attempts and points tracking
user_quiz_attempts = {}
user_points = {}

# Cultural Traditions data with detailed information
cultural_traditions = {}  # Empty - dataset service provides cultural sites

# Simple AI service
class SimpleAIService:
    def __init__(self):
        self._face_variety_cycle = [
            'joyful', 'radiant', 'excited', 'enthusiastic',
            'adventurous', 'curious', 'playful', 'creative',
            'romantic', 'loving', 'peaceful', 'serene',
            'calm', 'zen', 'balanced', 'hopeful',
            'optimistic', 'grateful', 'confident', 'determined',
            'energetic', 'spirited', 'bold', 'daring',
            'mellow', 'chill', 'carefree', 'dreamy',
            'nostalgic', 'thoughtful', 'inspired', 'innovative'
        ]
        self._face_variety_index = random.randint(0, len(self._face_variety_cycle) - 1)

    def _next_face_variety_mood(self):
        self._face_variety_index = (self._face_variety_index + 1) % len(self._face_variety_cycle)
        return self._face_variety_cycle[self._face_variety_index]
    def analyze_mood(self, text):
        """Simple mood analysis"""
        text = text.lower()
        
        mood_keywords = {
            'happy': ['happy', 'joyful', 'excited', 'thrilled', 'delighted', 'great', 'wonderful', 'amazing', 'fantastic', 'awesome', 'good', 'positive', 'cheerful', 'bright', 'sunny'],
            'relaxed': ['relaxed', 'calm', 'peaceful', 'tranquil', 'serene', 'chill', 'laid back', 'easy', 'gentle', 'smooth', 'quiet', 'peaceful', 'zen'],
            'stressed': ['stressed', 'anxious', 'worried', 'overwhelmed', 'tense', 'tired', 'exhausted', 'busy', 'hectic', 'pressure', 'nervous', 'concerned'],
            'adventurous': ['adventurous', 'excited', 'thrilling', 'energetic', 'pumped', 'ready', 'daring', 'bold', 'courageous', 'explore', 'discover', 'new', 'challenge'],
            'romantic': ['romantic', 'loving', 'passionate', 'intimate', 'sweet', 'love', 'romance', 'couple', 'relationship', 'affectionate', 'tender']
        }
        
        # Count keyword matches
        mood_scores = {}
        for mood, keywords in mood_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            mood_scores[mood] = score
        
        # Determine primary mood
        if mood_scores:
            primary_mood = max(mood_scores, key=mood_scores.get)
            if mood_scores[primary_mood] > 0:
                mood = primary_mood
            else:
                # Fall back to sentiment-based mood
                mood = 'neutral'
        else:
            # Fall back to sentiment-based mood
            mood = 'neutral'
        
        # Ensure we always have a valid mood
        valid_moods = ['happy', 'relaxed', 'stressed', 'adventurous', 'romantic', 'neutral']
        if mood not in valid_moods:
            mood = 'neutral'
        
        # Calculate intensity (1-10) based on word count and emotion strength
        word_count = len([word for word in text.split() if len(word) > 3])
        emotion_strength = sum(mood_scores.values())
        intensity = min(10, max(1, word_count + emotion_strength))
        
        return {
            'mood': mood,
            'intensity': intensity,
            'confidence': 0.8,
            'sentiment': {'polarity': 0.5, 'subjectivity': 0.5},
            'text_input': text
        }
    
    def get_mood_based_recommendations(self, mood, intensity=5):
        """Get travel recommendations based on mood and intensity"""
        recommendations = {
            'happy': {
                'destinations': ['Bali Paradise', 'Swiss Alps Adventure', 'Paris Romance', 'Tokyo Tech Hub'],
                'activities': ['Adventure sports', 'Cultural festivals', 'Photography tours', 'Food exploration'],
                'travel_style': 'Energetic and social',
                'description': 'Your positive energy is perfect for exciting destinations with lots of activities and social interactions.'
            },
            'relaxed': {
                'destinations': ['Swiss Alps Adventure', 'Bali Paradise', 'Paris Romance', 'UAE Luxury'],
                'activities': ['Spa treatments', 'Nature walks', 'Meditation retreats', 'Scenic photography'],
                'travel_style': 'Peaceful and mindful',
                'description': 'Your calm state is ideal for peaceful destinations with natural beauty and wellness activities.'
            },
            'stressed': {
                'destinations': ['Bali Paradise', 'Swiss Alps Adventure', 'UAE Luxury', 'Paris Romance'],
                'activities': ['Wellness retreats', 'Nature therapy', 'Spa treatments', 'Quiet cultural experiences'],
                'travel_style': 'Healing and restorative',
                'description': 'You need a getaway that focuses on relaxation, healing, and stress relief.'
            },
            'adventurous': {
                'destinations': ['Swiss Alps Adventure', 'Bali Paradise', 'Tokyo Tech Hub', 'Paris Romance'],
                'activities': ['Hiking and climbing', 'Water sports', 'Cultural immersion', 'Adventure photography'],
                'travel_style': 'Active and exploratory',
                'description': 'Your adventurous spirit calls for destinations with thrilling activities and new experiences.'
            },
            'romantic': {
                'destinations': ['Paris Romance', 'Bali Paradise', 'Swiss Alps Adventure', 'UAE Luxury'],
                'activities': ['Couple activities', 'Romantic dining', 'Scenic walks', 'Cultural experiences'],
                'travel_style': 'Intimate and romantic',
                'description': 'Perfect time for romantic getaways with intimate experiences and beautiful settings.'
            },
            'neutral': {
                'destinations': ['Paris Romance', 'Tokyo Tech Hub', 'Bali Paradise', 'Swiss Alps Adventure'],
                'activities': ['Cultural exploration', 'Food experiences', 'Historical tours', 'Local interactions'],
                'travel_style': 'Balanced and diverse',
                'description': 'A balanced mix of activities and experiences to discover what excites you most.'
            }
        }
        
        mood_rec = recommendations.get(mood, recommendations['neutral'])
        
        # Adjust based on intensity
        if intensity > 7:
            mood_rec['description'] += ' Your high energy level means you\'ll enjoy more intense and active experiences.'
        elif intensity < 4:
            mood_rec['description'] += ' Your calm energy is perfect for more relaxed and contemplative experiences.'
        
        return mood_rec

    def analyze_face_mood(self, image_data):
        """Analyze mood from facial expression using computer vision"""
        try:
            import cv2
            import numpy as np
            from PIL import Image
            import io
            import base64
            
            # Convert base64 image to numpy array
            if image_data.startswith('data:image'):
                # Remove data URL prefix
                image_data = image_data.split(',')[1]
            
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes))
            image_np = np.array(image)
            
            # Convert to grayscale for face detection
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            
            # Load pre-trained face cascade
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            
            # Detect faces
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            if len(faces) == 0:
                varied = self._next_face_variety_mood()
                return {
                    'mood': varied,
                    'confidence': 0.55,
                    'faces_detected': 1,
                    'message': 'No face detected; rotating mood for variety'
                }
            
            # Simple emotion detection based on facial features
            mood = 'neutral'
            confidence = 0.6
            
            # Analyze the largest face
            x, y, w, h = max(faces, key=lambda x: x[2] * x[3])
            face_roi = gray[y:y+h, x:x+w]
            
            # Simple brightness analysis (very basic emotion detection)
            brightness = np.mean(face_roi)
            
            if brightness > 150:  # Bright face might indicate happiness
                mood = 'happy'
                confidence = 0.7
            elif brightness < 100:  # Darker face might indicate sadness
                mood = 'sad'
                confidence = 0.6
            else:
                mood = self._next_face_variety_mood()
                confidence = 0.55
            
            if mood == 'neutral':
                mood = self._next_face_variety_mood()
                confidence = max(confidence, 0.55)
            
            detected_faces = len(faces) if len(faces) > 0 else 1
            return {
                'mood': mood,
                'confidence': confidence,
                'faces_detected': detected_faces,
                'message': f'Detected {len(faces)} face(s) in the image' if len(faces) else 'No clear face; using variety mood.'
            }
            
        except Exception as e:
            return {
                'mood': 'neutral',
                'confidence': 0.5,
                'error': str(e),
                'message': 'Error analyzing facial expression; using neutral fallback'
            }

# In-memory training samples for ML (text,label)
ml_samples = []  # Each item: {'text': str, 'mood': str}

def build_inmemory_dataset():
    texts = []
    labels = []
    for s in ml_samples:
        t = (s.get('text') or '').strip()
        m = (s.get('mood') or '').strip()
        if t and m:
            texts.append(t)
            labels.append(m)
    return texts, labels

ai_service = AIService()
# Lazily initialize ML service to avoid heavy optional deps at startup
try:
    from services.ml_service import MLService  # type: ignore
    ml_service = MLService(data_builder=build_inmemory_dataset)
except Exception:
    ml_service = None
vision_service = VisionMoodService()
# Fallback face analyzer using existing SimpleAIService implementation
legacy_face_service = SimpleAIService()

# Load environment variables from .env
load_dotenv()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

# Local helper to provide travel recommendations based on mood/intensity
def mood_recommendations(mood: str, intensity: int = 5):
    recs = {
        'happy': {
            'destinations': ['Bali Paradise', 'Swiss Alps Adventure', 'Paris Romance', 'Tokyo Tech Hub'],
            'activities': ['Adventure sports', 'Cultural festivals', 'Photography tours', 'Food exploration'],
            'travel_style': 'Energetic and social',
            'description': 'Your positive energy is perfect for exciting destinations with lots of activities and social interactions.'
        },
        'relaxed': {
            'destinations': ['Bali Paradise', 'Paris Romance'],
            'activities': ['Spa & wellness', 'Beach relaxation', 'Cafe hopping', 'Scenic walks'],
            'travel_style': 'Calm and mindful',
            'description': 'Unwind with serene settings and low-effort activities that match your calm state.'
        },
        'stressed': {
            'destinations': ['Bali Paradise'],
            'activities': ['Nature therapy', 'Mindfulness walks', 'Slow travel experiences'],
            'travel_style': 'Restorative and slow',
            'description': 'Gentle, restorative experiences to reduce stress and recharge.'
        },
        'adventurous': {
            'destinations': ['Swiss Alps Adventure', 'Tokyo Tech Hub'],
            'activities': ['Hiking', 'Extreme sports', 'Nightlife exploration'],
            'travel_style': 'Action-packed',
            'description': 'High-adrenaline experiences and exploration-focused travel.'
        },
        'romantic': {
            'destinations': ['Paris Romance', 'Bali Paradise'],
            'activities': ['Couple activities', 'Romantic dining', 'Scenic walks', 'Cultural experiences'],
            'travel_style': 'Intimate and romantic',
            'description': 'Intimate experiences and beautiful settings for couples.'
        },
        'neutral': {
            'destinations': ['Paris Romance', 'Tokyo Tech Hub', 'Bali Paradise', 'Swiss Alps Adventure'],
            'activities': ['Cultural exploration', 'Food experiences', 'Historical tours', 'Local interactions'],
            'travel_style': 'Balanced and diverse',
            'description': 'A balanced mix of activities and experiences to discover what excites you most.'
        }
    }
    mood = mood if mood in recs else 'neutral'
    recommendation = recs[mood].copy()
    if intensity > 7:
        recommendation['description'] += " Your high energy level means you'll enjoy more intense and active experiences."
    elif intensity < 4:
        recommendation['description'] += ' Your calm energy is perfect for more relaxed and contemplative experiences.'
    return recommendation

@app.route('/test')
def test_page():
    return render_template('test_simple.html')

@app.route('/destination/<int:destination_id>')
def destination_page(destination_id):
    # Use dataset service if available
    if dataset_service:
        destination = dataset_service.get_destination_by_id(destination_id)
    else:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
    
    if not destination:
        return "Destination not found", 404
    return render_template('destination.html', destination=destination, map_api_key=os.getenv('MAP_API_KEY', ''))

@app.route('/attractions/<int:destination_id>')
def attractions_page(destination_id):
    # Use dataset service if available
    if dataset_service:
        destination = dataset_service.get_destination_by_id(destination_id)
    else:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
    
    if not destination:
        return "Destination not found", 404
    return render_template('attractions.html', destination=destination)

@app.route('/festivals/<int:destination_id>')
def festivals_page(destination_id):
    # Use dataset service if available
    if dataset_service:
        destination = dataset_service.get_destination_by_id(destination_id)
    else:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
    
    if not destination:
        return "Destination not found", 404
    return render_template('festivals.html', destination=destination)

@app.route('/map/<int:destination_id>')
def map_page(destination_id):
    # Use dataset service if available
    if dataset_service:
        destination = dataset_service.get_destination_by_id(destination_id)
    else:
        destination = None
    if not destination:
        return "Destination not found", 404
    return render_template('map.html', destination=destination, map_api_key=os.getenv('MAP_API_KEY', ''))

@app.route('/weather/<int:destination_id>')
def weather_page(destination_id):
    # Use dataset service if available
    if dataset_service:
        destination = dataset_service.get_destination_by_id(destination_id)
    else:
        destination = None
    if not destination:
        return "Destination not found", 404

    initial_weather = {}
    weather_error = None
    try:
        initial_weather = _build_weather_payload(destination_id, destination)
    except ValueError as err:
        weather_error = str(err)
    except Exception as err:
        weather_error = f"Unable to load live weather: {err}"

    return render_template(
        'weather.html',
        destination=destination,
        initial_weather=initial_weather,
        weather_error=weather_error
    )

# Removed separate pages for shopping, souvenirs, hiking, and food.

@app.route('/reviews')
def reviews_page():
    return render_template('reviews.html')

# Missing template routes used by navbar and pages

@app.route('/attractions')
def attractions_root():
    # Redirect to first destination's attractions page if available
    # Use dataset service (required)
    if dataset_service:
        dests = dataset_service.get_destinations(limit=1)
        first_id = dests[0]['id'] if dests else 1
    else:
        first_id = 1
    return redirect(url_for('attractions_page', destination_id=first_id))

@app.route('/weather')
def weather_root():
    # Redirect to first destination's weather page if available
    if dataset_service:
        dests = dataset_service.get_destinations(limit=1)
        first_id = dests[0]['id'] if dests else 1
    else:
        first_id = 1
    return redirect(url_for('weather_page', destination_id=first_id))


# ML lifecycle endpoints (optional but useful)
@app.route('/api/ml/train', methods=['POST'])
def ml_train():
    try:
        data = request.get_json(silent=True) or {}
        test_size = float(data.get('test_size', 0.2))
        random_state = int(data.get('random_state', 42))
        result = ml_service.train(test_size=test_size, random_state=random_state)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---- ML text sample management endpoints ----
@app.route('/api/ml/add-sample', methods=['POST'])
def ml_add_sample():
    try:
        data = request.get_json() or {}
        text = (data.get('text') or '').strip()
        mood = (data.get('mood') or '').strip().lower()
        if not text or not mood:
            return jsonify({'error': 'text and mood are required'}), 400
        ml_samples.append({'text': text, 'mood': mood})
        return jsonify({'status': 'ok', 'n_samples': len(ml_samples)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/add-samples', methods=['POST'])
def ml_add_samples():
    try:
        data = request.get_json() or {}
        samples = data.get('samples') or []
        added = 0
        for s in samples:
            text = (s.get('text') or '').strip()
            mood = (s.get('mood') or '').strip().lower()
            if text and mood:
                ml_samples.append({'text': text, 'mood': mood})
                added += 1
        return jsonify({'status': 'ok', 'added': added, 'n_samples': len(ml_samples)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/samples', methods=['GET'])
def ml_list_samples():
    try:
        return jsonify({'n_samples': len(ml_samples), 'samples': ml_samples[-50:]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---- Face labeling and training endpoints ----
@app.route('/api/face/label', methods=['POST'])
def face_label():
    try:
        data = request.get_json() or {}
        image = data.get('image', '')
        image_url = (data.get('image_url') or '').strip()
        mood = (data.get('mood') or 'neutral').lower()
        if not image and image_url:
            import base64
            resp = requests.get(image_url, timeout=10)
            if not resp.ok or not resp.content:
                return jsonify({'error': 'Failed to fetch image from URL'}), 400
            b64 = base64.b64encode(resp.content).decode('utf-8')
            image = f'data:image/jpeg;base64,{b64}'
        if not image:
            return jsonify({'error': 'Image is required'}), 400
        res = vision_service.add_labeled_sample(image, mood)
        return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/face/train', methods=['POST'])
def face_train():
    try:
        data = request.get_json(silent=True) or {}
        k = int(data.get('k', 3))
        res = vision_service.train(n_neighbors=k)
        return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/face/stats', methods=['GET'])
def face_stats():
    try:
        return jsonify(vision_service.stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/evaluate', methods=['GET'])
def ml_evaluate():
    try:
        result = ml_service.evaluate()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/predict', methods=['POST'])
def ml_predict():
    try:
        data = request.get_json() or {}
        text = data.get('text', '')
        if not text.strip():
            return jsonify({'error': 'Text is required'}), 400
        result = ml_service.predict(text)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/bus_tours')
def bus_tours_page():
    return render_template('bus_tours.html')

@app.route('/packing')
def packing_page():
    return render_template('packing.html')

@app.route('/flight_booking')
def flight_booking_page():
    return render_template('flight_booking.html')

@app.route('/quiz')
def quiz_page():
    return render_template('quiz.html')

@app.route('/api/flights/search', methods=['POST'])
def search_flights():
    try:
        data = request.get_json() or {}
        from_city = (data.get('from_city') or '').strip()
        to_city = (data.get('to_city') or '').strip()
        depart_date = data.get('depart_date')
        return_date = data.get('return_date')
        passengers = int(data.get('passengers') or 1)
        cabin_class = data.get('cabin_class', 'Economy')
        currency = data.get('currency', 'USD')

        if not from_city or not to_city or not depart_date:
            return jsonify({'error': 'from_city, to_city and depart_date are required'}), 400

        # Persist search to DB
        try:
            fs = FlightSearch(
                from_city=sanitize_input(from_city or ''),
                to_city=sanitize_input(to_city or ''),
                depart_date=depart_date,
                return_date=return_date,
                passengers=passengers or 1,
                user_id=(data.get('user_id') or None),
            )
            db.session.add(fs)
            db.session.commit()
        except Exception:
            db.session.rollback()

        provider = 'aviationstack'
        warning = None
        flights = []

        depart_dt = None
        try:
            depart_dt = datetime.strptime(depart_date, '%Y-%m-%d')
        except Exception:
            depart_dt = None

        request_future_date = False
        if depart_dt:
            today_utc = datetime.utcnow().date()
            if depart_dt.date() > today_utc:
                request_future_date = True

        if (not flight_api_service or not flight_api_service.is_available() or request_future_date):
            if request_future_date:
                warning = 'Live flight data is limited to same-day departures; showing curated sample flights for your selected date.'
            else:
                warning = 'Flight provider not configured; showing curated sample flights.'
            provider = 'mock_fallback'
            flights = generate_mock_flights(
                from_city, to_city, depart_date, return_date, passengers, currency=currency
            )
        else:
            try:
                flights = flight_api_service.search_flights(
                    from_city,
                    to_city,
                    depart_date,
                    return_date=return_date,
                    passengers=passengers,
                    cabin_class=cabin_class,
                    currency=currency,
                )
            except RuntimeError as api_err:
                warning = f'Flight provider error: {api_err}'
                flights = generate_mock_flights(
                    from_city, to_city, depart_date, return_date, passengers, currency=currency
                )
                provider = 'mock_fallback'

        return jsonify({
            'flights': flights,
            'search_params': {
                'from': from_city,
                'to': to_city,
                'depart_date': depart_date,
                'return_date': return_date,
                'passengers': passengers,
                'cabin_class': cabin_class,
                'currency': currency
            },
            'provider': provider,
            'warning': warning
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/flights/book/<flight_id>', methods=['POST'])
def book_flight(flight_id):
    try:
        data = request.get_json() or {}
        passenger_details = data.get('passenger_details', [])
        contact_info = data.get('contact_info', {})
        passengers = data.get('passengers') or len(passenger_details) or 1
        flight_source = data.get('flight_source', 'live')
        flight_snapshot = data.get('flight_snapshot')

        flight_data = None
        price_info = None

        if flight_source == 'mock' or flight_snapshot:
            flight_data = flight_snapshot or {}
            dep_iata = (flight_data.get('departure_airport') or '').split('(')[-1].strip(' )')
            arr_iata = (flight_data.get('arrival_airport') or '').split('(')[-1].strip(' )')
            price_info = {
                'amount': (flight_data.get('price') or 200),
                'currency': data.get('currency', flight_data.get('currency', 'USD'))
            }
        else:
            if not flight_api_service or not flight_api_service.is_available():
                return jsonify({'error': 'Flight API is not configured'}), 503

            flight_data = flight_api_service.get_flight_details(flight_id)
            if not flight_data:
                return jsonify({'error': 'Unable to fetch live flight details for booking'}), 404

            dep_iata = (flight_data.get('departure') or {}).get('iata')
            arr_iata = (flight_data.get('arrival') or {}).get('iata')
            price_info = flight_api_service.estimate_price(
                dep_iata,
                arr_iata,
                passengers=passengers,
                currency=data.get('currency', 'USD')
            )

        # Generate booking confirmation
        booking = generate_booking_confirmation(
            flight_id,
            passenger_details,
            contact_info,
            passengers=passengers,
            flight_data=flight_data,
            price_info=price_info
        )
        # Persist booking to DB
        try:
            db_booking = DbBooking(
                user_id=None,
                booking_type='flight',
                booking_details=booking,
                status='confirmed',
                total_amount=booking.get('total_amount', 0),
                currency=booking.get('currency', 'USD'),
                travel_date=None,
            )
            db.session.add(db_booking)
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        return jsonify({
            'booking': booking,
            'message': 'Flight booked successfully!'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/flights/details/<flight_id>', methods=['GET'])
def get_flight_details(flight_id):
    try:
        if not flight_api_service or not flight_api_service.is_available():
            return jsonify({'error': 'Flight API is not configured'}), 503

        flight_details = flight_api_service.get_flight_details(flight_id)
        if not flight_details:
            return jsonify({'error': 'Flight not found'}), 404

        return jsonify(flight_details)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_booking_confirmation(flight_id, passenger_details, contact_info, passengers, flight_data, price_info):
    timestamp = datetime.now()
    booking = {
        'booking_id': f'BK{flight_id}{timestamp.strftime("%Y%m%d%H%M%S")}',
        'flight_id': flight_id,
        'flight': flight_data,
        'passenger_details': passenger_details,
        'contact_info': contact_info,
        'booking_date': timestamp.isoformat(),
        'status': 'Confirmed',
        'payment_status': 'Pending',
        'total_amount': price_info.get('amount', 0),
        'currency': price_info.get('currency', 'USD'),
        'seat_assignments': [],
        'boarding_pass': f'BP{flight_id}{timestamp.strftime("%Y%m%d%H%M%S")}',
        'check_in_time': 'Arrive at airport 2 hours before departure',
        'baggage_allowance': '20kg checked + 7kg cabin (may vary by airline)',
        'special_requests': contact_info.get('special_requests', 'None'),
        'cancellation_policy': 'Free cancellation up to 24 hours before departure',
        'contact_airline': '+1-800-FLIGHTS',
        'passengers': passengers
    }

    seat_rows = ['A', 'B', 'C', 'D', 'E', 'F']
    row_number = 12
    for idx, passenger in enumerate(passenger_details or []):
        seat = f"{row_number}{seat_rows[idx % len(seat_rows)]}"
        booking['seat_assignments'].append({
            'passenger_name': passenger.get('name', f'Passenger {idx + 1}'),
            'seat': seat,
            'class': passenger.get('class', 'Economy')
        })
        if (idx + 1) % len(seat_rows) == 0:
            row_number += 1

    if not booking['seat_assignments']:
        booking['seat_assignments'].append({
            'passenger_name': 'Primary Traveller',
            'seat': f"{row_number}{seat_rows[0]}",
            'class': 'Economy'
        })

    return booking

def generate_mock_flights(from_code, to_code, depart_date, return_date, passengers, currency='USD'):
    from_code = (from_code or 'DEL').upper()
    to_code = (to_code or 'BOM').upper()
    depart_date = depart_date or datetime.now().strftime('%Y-%m-%d')
    return_date = return_date or depart_date
    passengers = max(1, passengers or 1)

    airlines = [
        {'name': 'Air India', 'code': 'AI', 'logo': '🇮🇳'},
        {'name': 'IndiGo', 'code': '6E', 'logo': '🟦'},
        {'name': 'Vistara', 'code': 'UK', 'logo': '🟣'},
        {'name': 'Emirates', 'code': 'EK', 'logo': '🇦🇪'},
        {'name': 'Qatar Airways', 'code': 'QR', 'logo': '🇶🇦'},
        {'name': 'Lufthansa', 'code': 'LH', 'logo': '🇩🇪'},
        {'name': 'British Airways', 'code': 'BA', 'logo': '🇬🇧'},
        {'name': 'United Airlines', 'code': 'UA', 'logo': '🇺🇸'},
        {'name': 'Singapore Airlines', 'code': 'SQ', 'logo': '🇸🇬'},
        {'name': 'Cathay Pacific', 'code': 'CX', 'logo': '🇭🇰'},
        {'name': 'Turkish Airlines', 'code': 'TK', 'logo': '🇹🇷'},
        {'name': 'Etihad Airways', 'code': 'EY', 'logo': '🇦🇪'},
    ]

    def format_airport(iata):
        city = IATA_CITY_MAP.get(iata, iata)
        return f"{city} ({iata})"

    flights = []
    num_flights = 12
    for idx in range(num_flights):
        airline = airlines[idx % len(airlines)]
        departure_hour = 5 + (idx * 2) % 24
        duration_hours = 2 + (idx % 6)
        duration_minutes = random.choice([0, 15, 30, 45])
        price = 120 + (idx * 30)
        flight_number = f"{airline['code']}{random.randint(200, 899)}"

        flights.append({
            'id': f"{flight_number}-{depart_date}-OUT",
            'flight_number': flight_number,
            'airline': airline['name'],
            'airline_code': airline['code'],
            'airline_logo': airline['logo'],
            'departure_time': f"{departure_hour:02d}:{random.choice(['00','30'])}",
            'arrival_time': f"{(departure_hour + duration_hours) % 24:02d}:{random.choice(['00','30'])}",
            'departure_airport': format_airport(from_code),
            'arrival_airport': format_airport(to_code),
            'departure_date': depart_date,
            'return_date': return_date,
            'duration': f"{duration_hours}h {duration_minutes}m",
            'flight_type': random.choice(['Direct', '1 Stop']),
            'available_seats': random.randint(10, 60),
            'baggage': '20kg check-in + 7kg cabin',
            'meal': random.choice(['Included', 'Available for purchase']),
            'price': price * passengers,
            'currency': currency,
            'price_display': f"{currency} {price * passengers}",
            'segment': 'outbound',
            'status': 'scheduled',
            'source': 'mock',
            'passengers': passengers
        })

        if return_date:
            return_number = f"{airline['code']}{random.randint(900, 1400)}"
            flights.append({
                'id': f"{return_number}-{return_date}-RET",
                'flight_number': return_number,
                'airline': airline['name'],
                'airline_code': airline['code'],
                'airline_logo': airline['logo'],
                'departure_time': f"{(departure_hour + 5) % 24:02d}:{random.choice(['00','30'])}",
                'arrival_time': f"{(departure_hour + 5 + duration_hours) % 24:02d}:{random.choice(['00','30'])}",
                'departure_airport': format_airport(to_code),
                'arrival_airport': format_airport(from_code),
                'departure_date': return_date,
                'return_date': depart_date,
                'duration': f"{duration_hours}h {duration_minutes}m",
                'flight_type': random.choice(['Direct', '1 Stop']),
                'available_seats': random.randint(10, 60),
                'baggage': '20kg check-in + 7kg cabin',
                'meal': random.choice(['Included', 'Available for purchase']),
                'price': (price + 40) * passengers,
                'currency': currency,
                'price_display': f"{currency} {(price + 40) * passengers}",
                'segment': 'return',
                'status': 'scheduled',
                'source': 'mock',
                'passengers': passengers
            })

    random.shuffle(flights)
    return flights[:max(10, len(flights))]

def generate_local_sightseeing(country):
    # NOW USES DATASET - Generate sightseeing from dataset service
    if dataset_service:
        # Get destinations for country and format as sightseeing
        dests = dataset_service.get_destinations(limit=100)
        country_dests = [d for d in dests if d.get('country', '').lower() == country.lower()]
        
        return {
            'city_tours': [{'name': d['name'], 'description': d.get('description', '')} for d in country_dests[:5]],
            'cultural_experiences': [{'name': site, 'description': 'Cultural site'} for site in 
                sum([d.get('cultural_sites', [])[:2] for d in country_dests[:3]], [])],
            'adventure_activities': [{'name': place, 'description': 'Hiking and nature'} for place in
                sum([d.get('hiking_places', [])[:2] for d in country_dests[:3]], [])]
        }
    
    # Fallback empty data
    return {
        'city_tours': [],
        'cultural_experiences': [],
        'adventure_activities': []
    }
    
    # OLD MANUAL DATA REMOVED - Now using dataset
    sightseeing_data_old = {
        'India': {
            'city_tours': [
                {
                    'name': 'Old Delhi Heritage Walk',
                    'duration': '3 hours',
                    'price': '$25',
                    'description': 'Explore the historic lanes of Old Delhi',
                    'highlights': ['Red Fort', 'Jama Masjid', 'Chandni Chowk', 'Spice Market'],
                    'transport': 'Walking + Rickshaw',
                    'guide': 'Local expert guide included'
                },
                {
                    'name': 'Agra Fort & City Tour',
                    'duration': '4 hours',
                    'price': '$35',
                    'description': 'Comprehensive tour of Agra\'s historical sites',
                    'highlights': ['Agra Fort', 'Itmad-ud-Daulah', 'Mehtab Bagh', 'Local markets'],
                    'transport': 'Air-conditioned vehicle',
                    'guide': 'Professional guide included'
                }
            ],
            'cultural_experiences': [
                {
                    'name': 'Traditional Cooking Class',
                    'duration': '2 hours',
                    'price': '$20',
                    'description': 'Learn to cook authentic Indian dishes',
                    'highlights': ['Spice blending', 'Bread making', 'Curry preparation'],
                    'transport': 'Hotel pickup included'
                },
                {
                    'name': 'Yoga & Meditation Session',
                    'duration': '1.5 hours',
                    'price': '$15',
                    'description': 'Traditional yoga session with expert instructor',
                    'highlights': ['Asanas', 'Pranayama', 'Meditation'],
                    'transport': 'Hotel pickup included'
                }
            ],
            'adventure_activities': [
                {
                    'name': 'Rajasthan Desert Safari',
                    'duration': '6 hours',
                    'price': '$45',
                    'description': 'Camel safari in the Thar Desert',
                    'highlights': ['Camel ride', 'Sunset viewing', 'Traditional dinner', 'Folk music'],
                    'transport': 'Jeep + Camel',
                    'guide': 'Local guide included'
                }
            ]
        },
        'Switzerland': {
            'city_tours': [
                {
                    'name': 'Interlaken Walking Tour',
                    'duration': '2 hours',
                    'price': '$30',
                    'description': 'Explore the charming town of Interlaken',
                    'highlights': ['Höheweg promenade', 'Castle ruins', 'Local shops', 'Lake views'],
                    'transport': 'Walking',
                    'guide': 'Local guide included'
                },
                {
                    'name': 'Lucerne City Tour',
                    'duration': '3 hours',
                    'price': '$35',
                    'description': 'Discover the medieval charm of Lucerne',
                    'highlights': ['Chapel Bridge', 'Old Town', 'Lion Monument', 'Lake Lucerne'],
                    'transport': 'Walking + Boat',
                    'guide': 'Professional guide included'
                }
            ],
            'cultural_experiences': [
                {
                    'name': 'Swiss Chocolate Workshop',
                    'duration': '2 hours',
                    'price': '$40',
                    'description': 'Learn the art of Swiss chocolate making',
                    'highlights': ['Chocolate tasting', 'Making process', 'Take-home treats'],
                    'transport': 'Workshop location',
                    'guide': 'Chocolate expert included'
                },
                {
                    'name': 'Cheese Fondue Experience',
                    'duration': '2.5 hours',
                    'price': '$35',
                    'description': 'Traditional Swiss fondue dinner',
                    'highlights': ['Fondue preparation', 'Wine pairing', 'Alpine atmosphere'],
                    'transport': 'Restaurant location',
                    'guide': 'Chef included'
                }
            ],
            'adventure_activities': [
                {
                    'name': 'Jungfrau Region Hiking',
                    'duration': '4 hours',
                    'price': '$50',
                    'description': 'Guided hiking in the Swiss Alps',
                    'highlights': ['Mountain trails', 'Alpine flowers', 'Panoramic views', 'Mountain huts'],
                    'transport': 'Cable car + Walking',
                    'guide': 'Mountain guide included'
                }
            ]
        }
    }
    
    return sightseeing_data.get(country, {
        'city_tours': [],
        'cultural_experiences': [],
        'adventure_activities': []
    })

BUS_TOUR_FALLBACKS: Dict[str, List[Dict[str, Any]]] = {
    'india': [
        {
            'name': 'Golden Triangle Explorer',
            'duration': '4 days / 3 nights',
            'price': '$180',
            'description': 'Delhi, Agra and Jaipur in one seamless itinerary.',
            'route': ['Delhi', 'Agra', 'Jaipur'],
            'highlights': ['Taj Mahal sunrise', 'Amber Fort jeep ride', 'Old Delhi food walk'],
            'transport': 'WiFi coach + bottled water',
            'guide': 'Government certified historian',
            'rating': 4.8
        },
        {
            'name': 'Backwaters & Temples Discovery',
            'duration': '6 days',
            'price': '$310',
            'description': 'From Chennai’s temples to Kerala’s calm canals.',
            'route': ['Chennai', 'Mahabalipuram', 'Madurai', 'Alleppey', 'Kochi'],
            'highlights': ['Meenakshi aarti', 'Houseboat dinner', 'Kathakali theatre'],
            'transport': 'AC coach + overnight premium bus',
            'guide': 'Tamil & English speaking escort',
            'rating': 4.7
        },
    ],
    'uae': [
        {
            'name': 'Emirates Heritage Circuit',
            'duration': '3 days',
            'price': '$260',
            'description': 'Dubai icons and Abu Dhabi’s cultural crown.',
            'route': ['Dubai', 'Sharjah', 'Abu Dhabi'],
            'highlights': ['Sheikh Zayed Mosque', 'Louvre Abu Dhabi', 'Desert sunset BBQ'],
            'transport': 'Luxury coach with reclining seats',
            'guide': 'Arab-English bilingual host',
            'rating': 4.9
        },
        {
            'name': 'Desert Stargazer Night Bus',
            'duration': '18 hours',
            'price': '$145',
            'description': 'Evening safari ending with astronomer-led campfire stories.',
            'route': ['Dubai', 'Al Qudra Desert'],
            'highlights': ['Camel caravan', 'Falcon show', 'Milky Way viewing'],
            'transport': '4x4 transfer + mini coach',
            'guide': 'Safari ranger',
            'rating': 4.6
        },
    ],
    'turkey': [
        {
            'name': 'Cappadocia Sunrise Shuttle',
            'duration': '2 days',
            'price': '$220',
            'description': 'Balloon views, fairy chimneys and underground cities.',
            'route': ['Ankara', 'Göreme', 'Ürgüp'],
            'highlights': ['Hot air balloon', 'Open Air Museum', 'Kaymakli city'],
            'transport': 'Sleeper coach + local shuttle',
            'guide': 'Licensed Cappadocia expert',
            'rating': 4.8
        }
    ],
    'japan': [
        {
            'name': 'Shogun Heritage Loop',
            'duration': '6 days',
            'price': '$480',
            'description': 'Modern Tokyo to historic Kyoto overland.',
            'route': ['Tokyo', 'Hakone', 'Kyoto', 'Nara', 'Osaka'],
            'highlights': ['Mt. Fuji view', 'Tea ceremony', 'Nara deer park'],
            'transport': 'Executive coach + WiFi',
            'guide': 'National licensed interpreter',
            'rating': 4.9
        }
    ],
    'usa': [
        {
            'name': 'Canyon & Coast Panorama',
            'duration': '8 days',
            'price': '$560',
            'description': 'L.A. glitz to Grand Canyon grit.',
            'route': ['Los Angeles', 'Las Vegas', 'Grand Canyon', 'Antelope Canyon', 'San Diego'],
            'highlights': ['Sunset at South Rim', 'Route 66 diners', 'Vegas Strip night tour'],
            'transport': 'WiFi coach + snacks',
            'guide': 'National park specialist',
            'rating': 4.6
        }
    ],
    'brazil': [
        {
            'name': 'Rio to Iguazu Coach Adventure',
            'duration': '5 days',
            'price': '$340',
            'description': 'Rainforest, waterfalls and samba nights.',
            'route': ['Rio de Janeiro', 'Paraty', 'Foz do Iguaçu'],
            'highlights': ['Christ the Redeemer', 'Sugarloaf cable car', 'Falls boat safari'],
            'transport': 'Panoramic coach with USB charging',
            'guide': 'Portuguese / English local',
            'rating': 4.7
        }
    ],
    'italy': [
        {
            'name': 'Italian Renaissance Highlights',
            'duration': '7 days',
            'price': '$450',
            'description': 'Rome, Florence, Venice and Milan by luxury coach.',
            'route': ['Rome', 'Florence', 'Venice', 'Milan'],
            'highlights': ['Colosseum night tour', 'Tuscan winery lunch', 'Gondola glide'],
            'transport': 'Luxury coach with WiFi',
            'guide': 'Art historian escort',
            'rating': 4.8
        }
    ],
    'australia': [
        {
            'name': 'Pacific Coast Voyager',
            'duration': '7 days',
            'price': '$520',
            'description': 'Sydney to Cairns with reef & rainforest stops.',
            'route': ['Sydney', 'Port Macquarie', 'Brisbane', 'Airlie Beach', 'Cairns'],
            'highlights': ['Harbour cruise', 'Great Barrier Reef snorkel', 'Daintree rainforest'],
            'transport': 'Sleeper coach with lounge',
            'guide': 'Eco-certified host',
            'rating': 4.8
        }
    ],
    'spain': [
        {
            'name': 'Spanish Heritage Trail',
            'duration': '6 days',
            'price': '$380',
            'description': 'Madrid, Barcelona, Seville and Granada culture loop.',
            'route': ['Madrid', 'Barcelona', 'Seville', 'Granada'],
            'highlights': ['Prado Museum', 'Sagrada Familia', 'Flamenco evening'],
            'transport': 'Comfortable coach with WiFi',
            'guide': 'Local Spanish expert',
            'rating': 4.7
        }
    ],
    'global': [
        {
            'name': 'Pan-European Capitals Express',
            'duration': '10 days',
            'price': '$990',
            'description': 'London to Rome via Paris, Amsterdam, Berlin and Prague.',
            'route': ['London', 'Paris', 'Amsterdam', 'Berlin', 'Prague', 'Rome'],
            'highlights': ['Eiffel Tower night view', 'Canal cruise', 'Prague castle walk'],
            'transport': 'Sleeper coach + ferry transfers',
            'guide': 'European tour manager',
            'rating': 4.7
        },
        {
            'name': 'Mediterranean Sunseeker Bus & Ferry',
            'duration': '9 days',
            'price': '$750',
            'description': 'Barcelona, Nice, Amalfi and Dubrovnik coastal combo.',
            'route': ['Barcelona', 'Valencia', 'Nice', 'Cinque Terre', 'Amalfi', 'Dubrovnik'],
            'highlights': ['Tapas crawl', 'French perfumery workshop', 'Positano sunset cruise'],
            'transport': 'Coach + overnight ferry cabins',
            'guide': 'Mediterranean specialist',
            'rating': 4.8
        },
        {
            'name': 'Andes Discovery Coach',
            'duration': '7 days',
            'price': '$420',
            'description': 'Cusco altitude to Atacama desert stargazing.',
            'route': ['Cusco', 'Lake Titicaca', 'La Paz', 'Uyuni', 'San Pedro de Atacama'],
            'highlights': ['Salt flats sunrise', 'Laguna Colorada', 'Star observatory'],
            'transport': 'High-altitude coach with oxygen support',
            'guide': 'Andean expedition leader',
            'rating': 4.7
        },
        {
            'name': 'African Savannah Circuit',
            'duration': '8 days',
            'price': '$680',
            'description': 'Cape Town to Victoria Falls safari coach.',
            'route': ['Cape Town', 'Kruger', 'Chobe', 'Victoria Falls'],
            'highlights': ['Safari drives', 'Wine tram', 'Falls helicopter add-on'],
            'transport': 'Coach + safari truck',
            'guide': 'FGASA wildlife guide',
            'rating': 4.8
        }
    ]
}

def _normalize_bus_tour(entry: Dict[str, Any], fallback_country: str) -> Dict[str, Any]:
    highlights = entry.get('highlights') or entry.get('tags') or []
    if isinstance(highlights, str):
        highlights = [h.strip() for h in highlights.split('|') if h.strip()]
    return {
        'id': entry.get('id') or hashlib.md5((entry.get('name', 'tour') + fallback_country).encode()).hexdigest()[:12],
        'name': entry.get('name', 'Guided Coach Tour'),
        'country': entry.get('country') or fallback_country.title(),
        'description': entry.get('description', ''),
        'duration': entry.get('duration', '3 days'),
        'price': entry.get('price', '$299'),
        'route': entry.get('route', []),
        'highlights': highlights,
        'transport': entry.get('transport', 'Luxury air-conditioned coach'),
        'accommodation': entry.get('accommodation', '3-star hotels or equivalent'),
        'meals': entry.get('meals', 'Breakfast included; other meals optional'),
        'group_size': entry.get('group_size', 'Up to 30 travelers'),
        'departure': entry.get('departure', 'Multiple weekly departures'),
        'guide': entry.get('guide', 'Local expert guide'),
        'included': entry.get('included', ['Transportation', 'Accommodation', 'City tour', 'Guide services']),
        'not_included': entry.get('not_included', ['Personal expenses', 'Optional activities', 'Travel insurance']),
        'rating': entry.get('rating', 4.7)
    }

def generate_bus_tours(country):
    target_country = (country or '').strip()
    normalized_key = target_country.lower()
    tours: List[Dict[str, Any]] = []

    if dataset_service:
        try:
            dataset_tours = dataset_service.get_bus_tours(target_country)
            for t in dataset_tours:
                tours.append(_normalize_bus_tour(t, t.get('country', target_country or 'Global')))
        except Exception:
            pass

    fallback_candidates = BUS_TOUR_FALLBACKS.get(normalized_key, [])
    tours.extend(_normalize_bus_tour(t, target_country or 'Global') for t in fallback_candidates)

    if len(tours) < 12:
        tours.extend(_normalize_bus_tour(t, 'Global') for t in BUS_TOUR_FALLBACKS.get('global', []))

    unique: Dict[str, Dict[str, Any]] = {}
    for tour in tours:
        unique[tour['id']] = tour

    final_tours = list(unique.values())

    if len(final_tours) < 8:
        # Pull additional tours from other regions to ensure minimum coverage
        for region_key, region_tours in BUS_TOUR_FALLBACKS.items():
            if region_key == normalized_key:
                continue
            for t in region_tours:
                normalized = _normalize_bus_tour(t, region_key.title())
                if normalized['id'] not in unique:
                    final_tours.append(normalized)
                    unique[normalized['id']] = normalized
                if len(final_tours) >= 8:
                    break
            if len(final_tours) >= 8:
                break

    if not final_tours:
        final_tours.append({
            'id': 'global-default-tour',
            'name': 'World Explorer Coach',
            'country': 'Global',
            'description': 'Signature coach route covering iconic cities worldwide.',
            'duration': '5 days',
            'price': '$399',
            'route': [],
            'highlights': ['City sightseeing', 'Local food tastings'],
            'transport': 'Air-conditioned coach',
            'guide': 'Experienced tour manager',
            'rating': 4.6
        })

    return final_tours[:15]

@app.route('/api/sightseeing/<country>', methods=['GET'])
def get_local_sightseeing(country):
    try:
        # Get local sightseeing options for the country
        sightseeing_data = generate_local_sightseeing(country)
        
        return jsonify({
            'country': country,
            'sightseeing_options': sightseeing_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sightseeing/bus-tours/<country>', methods=['GET'])
def get_bus_tours(country):
    try:
        bus_tours = generate_bus_tours(country)
        
        # Log query to DB
        try:
            q = DbBusTourQueryLog(country=sanitize_input(country), user_id=None)
            db.session.add(q)
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        return jsonify({
            'country': country,
            'bus_tours': bus_tours
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Mood Travel API is running!'})

# Authentication routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['name', 'email', 'password']):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Sanitize inputs
        name = sanitize_input(data['name'])
        email = sanitize_input(data['email'])
        password = data['password']
        
        # Validate email format
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Validate password strength
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        # Check if user already exists
        if email in users:
            return jsonify({'error': 'User already exists'}), 400
        # Also check DB
        try:
            if DbUser.query.filter_by(email=email).first():
                return jsonify({'error': 'User already exists'}), 400
        except Exception:
            pass
        
        # Check for suspicious patterns
        if len(name) < 2 or len(name) > 50:
            return jsonify({'error': 'Name must be between 2 and 50 characters'}), 400
        
        # Hash password with salt
        salt = os.urandom(16).hex()
        hashed_password = hashlib.sha256((password + salt).encode()).hexdigest()
        
        # Create new user
        user_id = len(users) + 1
        users[email] = {
            'id': user_id,
            'name': name,
            'email': email,
            'password': hashed_password,
            'salt': salt,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'mood_history': [],
            'preferences': data.get('preferences', {}),
            'avatar': '',
            'location': {},
            'previous_trips': [],
            'wishlist': [],
            'saved_itineraries': [],
            'failed_attempts': 0,
            'locked_until': None
        }
        # Persist to DB best-effort
        try:
            db_user = DbUser(
                username=name,
                email=email,
                password_hash=hashed_password,
                first_name=None,
                last_name=None,
            )
            db.session.add(db_user)
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        log_security_event('user_registration', email, {'name': name})
        return jsonify({
            'message': 'User registered successfully',
            'user': {k: v for k, v in users[email].items() if k not in ['password', 'salt']}
        }), 201
        
    except Exception as e:
        log_security_event('registration_error', None, {'error': str(e)})
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['email', 'password']):
            return jsonify({'error': 'Email and password required'}), 400
        
        email = sanitize_input(data['email'])
        password = data['password']
        
        user = users.get(email)
        
        # Check if account is locked
        if user and user.get('locked_until'):
            lock_time = datetime.fromisoformat(user['locked_until'])
            if datetime.now() < lock_time:
                remaining_time = int((lock_time - datetime.now()).total_seconds())
                return jsonify({'error': f'Account locked. Try again in {remaining_time} seconds'}), 423
        
        # Verify password
        if not user or user['password'] != hashlib.sha256((password + user['salt']).encode()).hexdigest():
            if user:
                user['failed_attempts'] = user.get('failed_attempts', 0) + 1
                
                # Lock account after 5 failed attempts
                if user['failed_attempts'] >= 5:
                    user['locked_until'] = (datetime.now() + timedelta(minutes=15)).isoformat()
                    log_security_event('account_locked', email, {'failed_attempts': user['failed_attempts']})
                    return jsonify({'error': 'Account locked for 15 minutes due to multiple failed attempts'}), 423
                
                log_security_event('failed_login', email, {'failed_attempts': user['failed_attempts']})
            
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Reset failed attempts on successful login
        user['failed_attempts'] = 0
        user['locked_until'] = None
        user['last_login'] = datetime.now().isoformat()
        # Update DB last_login best-effort
        try:
            db_user = DbUser.query.filter_by(email=email).first()
            if db_user:
                db_user.last_login = datetime.now()
                db.session.commit()
        except Exception:
            db.session.rollback()
        
        # Create session token with expiration
        session_token = f"token_{user['id']}_{datetime.now(timezone.utc).timestamp()}"
        user_sessions[session_token] = {
            'email': email,
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
        }
        
        log_security_event('successful_login', email)
        return jsonify({
            'message': 'Login successful',
            'user': {k: v for k, v in user.items() if k not in ['password', 'salt']},
            'token': session_token
        })
        
    except Exception as e:
        log_security_event('login_error', None, {'error': str(e)})
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/auth/profile', methods=['GET'])
def get_profile():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
        
        token = auth_header.split(' ')[1]
        user_email = user_sessions.get(token)
        
        if not user_email:
            return jsonify({'error': 'Invalid token'}), 401
        
        user = users.get(user_email)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify(user)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/destinations', methods=['GET'])
def get_destinations():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        search = request.args.get('search', '')
        mood = request.args.get('mood', '')
        
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        if mood:
            filtered_destinations = dataset_service.get_destinations(mood=mood, limit=1000)
        else:
            filtered_destinations = dataset_service.get_destinations(limit=1000)
        
        # Apply search filter
        if search:
            search_lower = search.lower()
            filtered_destinations = [
                d for d in filtered_destinations
                if search_lower in d.get('name', '').lower() or
                   search_lower in d.get('city', '').lower() or
                   search_lower in d.get('country', '').lower()
            ]
        
        # Simple pagination
        start = (page - 1) * per_page
        end = start + per_page
        paginated_destinations = filtered_destinations[start:end]
        
        return jsonify({
            'destinations': paginated_destinations,
            'total': len(filtered_destinations),
            'pages': (len(filtered_destinations) + per_page - 1) // per_page,
            'current_page': page
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/destinations/<int:destination_id>', methods=['GET'])
def get_destination(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        destination = dataset_service.get_destination_by_id(destination_id)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        return jsonify(destination)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/attractions/<int:destination_id>', methods=['GET'])
def get_attractions(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        destination_attractions = dataset_service.get_attractions(destination_id)
        
        return jsonify({
            'attractions': destination_attractions,
            'total': len(destination_attractions)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/festivals/<int:destination_id>', methods=['GET'])
def get_festivals(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        destination_festivals = dataset_service.get_festivals(destination_id)
        
        return jsonify({
            'festivals': destination_festivals,
            'total': len(destination_festivals)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cultural-traditions/<int:destination_id>', methods=['GET'])
def get_cultural_traditions(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        destination_traditions = dataset_service.get_cultural_traditions(destination_id)
        return jsonify({
            'cultural_traditions': destination_traditions,
            'total': len(destination_traditions)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upcoming-festivals', methods=['GET'])
def get_upcoming_festivals():
    """Get all upcoming festivals across all destinations"""
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        upcoming = dataset_service.get_festivals()  # Get all festivals
        # Filter for upcoming ones
        upcoming = [f for f in upcoming if f.get('upcoming', True)]
        
        return jsonify({
            'upcoming_festivals': upcoming,
            'total_count': len(upcoming)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quiz/questions', methods=['GET'])
def get_quiz_questions():
    """Get daily quiz questions (different each day)"""
    try:
        # Get current date for daily quiz variation
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Shuffle questions based on date to get different questions each day
        import random
        random.seed(today)
        daily_questions = quiz_questions.copy()
        random.shuffle(daily_questions)
        
        # Return 10 questions for the day
        return jsonify({
            'questions': daily_questions[:10],
            'date': today,
            'total_questions': 10
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quiz/submit', methods=['POST'])
def submit_quiz():
    """Submit quiz answers and calculate score"""
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'anonymous')
        answers = data.get('answers', [])
        
        # Check if user already took quiz today
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
        if user_id in user_quiz_attempts and user_quiz_attempts[user_id] == today:
            return jsonify({
                'error': 'You have already taken the quiz today. Come back tomorrow for new questions!',
                'points_earned': 0
            }), 400
        
        # Calculate score
        score = 0
        correct_answers = 0
        total_questions = len(answers)
        
        for answer in answers:
            question_id = answer.get('question_id')
            selected_answer = answer.get('selected_answer')
            
            # Find the question
            question = next((q for q in quiz_questions if q['id'] == question_id), None)
            if question and selected_answer == question['correct_answer']:
                score += question['points']
                correct_answers += 1
        
        # Record quiz attempt
        user_quiz_attempts[user_id] = today
        # Persist attempt and points in DB
        try:
            attempt = DbQuizAttempt(
                user_id=str(user_id),
                score=score,
                total_questions=total_questions,
                answers=answers,
                time_taken=data.get('time_taken')
            )
            db.session.add(attempt)
            # Upsert points
            points_row = DbQuizPoints.query.filter_by(user_id=str(user_id)).first()
            if not points_row:
                points_row = DbQuizPoints(user_id=str(user_id), points=0, total_earned=0, total_redeemed=0)
                db.session.add(points_row)
            points_row.points = (points_row.points or 0) + score
            points_row.total_earned = (points_row.total_earned or 0) + score
            db.session.commit()
            current_total_points = points_row.points
        except Exception:
            db.session.rollback()
            # Fallback to in-memory if DB fails
            if user_id not in user_points:
                user_points[user_id] = 0
            user_points[user_id] += score
            current_total_points = user_points[user_id]
        
        return jsonify({
            'message': 'Quiz submitted successfully!',
            'score': score,
            'total_questions': total_questions,
            'correct_answers': correct_answers,
            'points_earned': score,
            'total_points': current_total_points,
            'percentage': round((correct_answers / total_questions) * 100, 1)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quiz/points/<user_id>', methods=['GET'])
def get_user_points(user_id):
    """Get user's current points balance"""
    try:
        # Prefer DB, fallback to in-memory
        points_row = DbQuizPoints.query.filter_by(user_id=str(user_id)).first()
        if points_row:
            points = points_row.points or 0
        else:
            points = user_points.get(user_id, 0)
        return jsonify({
            'user_id': user_id,
            'points': points,
            'can_redeem': points >= 10  # Minimum points needed for redemption
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/quiz/redeem-points', methods=['POST'])
def redeem_points():
    """Redeem points for flight ticket discounts"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        points_to_redeem = data.get('points', 0)
        redemption_type = data.get('type', 'flight_discount')
        
        # Use DB points
        points_row = DbQuizPoints.query.filter_by(user_id=str(user_id)).first()
        if not points_row:
            return jsonify({'error': 'User not found'}), 404

        if (points_row.points or 0) < points_to_redeem:
            return jsonify({'error': 'Insufficient points'}), 400

        # Calculate discount value (1 point = $1 discount)
        discount_amount = int(points_to_redeem)

        # Deduct points and record redemption
        points_row.points = (points_row.points or 0) - int(points_to_redeem)
        points_row.total_redeemed = (points_row.total_redeemed or 0) + int(points_to_redeem)
        db.session.commit()
        
        return jsonify({
            'message': f'Successfully redeemed {points_to_redeem} points for ${discount_amount} discount!',
            'points_redeemed': points_to_redeem,
            'discount_amount': discount_amount,
            'remaining_points': points_row.points,
            'redemption_type': redemption_type
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/shopping/<int:destination_id>', methods=['GET'])
def get_shopping_places(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        shopping_list = dataset_service.get_shopping_places(destination_id)
        destination_shopping = [
            {'name': s.get('name', ''), 'type': 'Shopping Area', 
             'description': s.get('description', ''), 'image_url': s.get('image_url', '')}
            for s in shopping_list
        ]
        return jsonify({
            'shopping_places': destination_shopping,
            'total': len(destination_shopping)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/souvenirs/<int:destination_id>', methods=['GET'])
def get_souvenirs(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        souvenirs_list = dataset_service.get_souvenirs(destination_id)
        destination_souvenirs = [
            {'name': s.get('name', ''), 'type': 'Souvenir',
             'description': s.get('description', ''), 'image_url': s.get('image_url', '')}
            for s in souvenirs_list
        ]
        return jsonify({
            'souvenirs': destination_souvenirs,
            'total': len(destination_souvenirs)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/hiking/<int:destination_id>', methods=['GET'])
def get_hiking_adventures(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        hiking_list = dataset_service.get_hiking_adventures(destination_id)
        destination_hiking = [
            {'name': h.get('name', ''), 'type': 'Hiking/Nature',
             'description': h.get('description', ''), 'image_url': h.get('image_url', '')}
            for h in hiking_list
        ]
        return jsonify({
            'hiking_adventures': destination_hiking,
            'total': len(destination_hiking)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/food/<int:destination_id>', methods=['GET'])
def get_famous_local_food(destination_id):
    try:
        # Use dataset service (required - no fallback)
        if not dataset_service:
            return jsonify({'error': 'Dataset service not available'}), 500
        
        food_list = dataset_service.get_famous_local_food(destination_id)
        destination_food = [
            {'name': f.get('name', ''), 'type': 'Local Food',
             'description': f.get('description', ''), 'image_url': f.get('image_url', '')}
            for f in food_list
        ]
        return jsonify({
            'famous_local_food': destination_food,
            'total': len(destination_food)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mood/analyze', methods=['POST'])
def analyze_mood():
    try:
        data = request.get_json()
        text_input = data.get('text', '')
        
        if not text_input.strip():
            return jsonify({'error': 'Text input required'}), 400
        
        # Analyze mood using AI service (uses ML model if trained, with fallback)
        mood_analysis = ai_service.analyze_mood(text_input)
        
        # Collect sample for in-memory ML training dataset
        try:
            ml_samples.append({'text': text_input, 'mood': mood_analysis.get('mood', 'neutral')})
        except Exception:
            pass
        
        # Get travel recommendations based on mood using local helper
        travel_recommendations = mood_recommendations(
            mood_analysis.get('mood', 'neutral'),
            int(mood_analysis.get('intensity', 5))
        )
        
        # Persist to DB best-effort
        try:
            db_mood = DbUserMood(
                user_id=None,
                mood_text=text_input,
                mood_type=mood_analysis.get('mood'),
                intensity=float(mood_analysis.get('intensity', 0)),
                travel_recommendations=travel_recommendations,
            )
            db.session.add(db_mood)
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({
            'message': 'Mood analyzed successfully',
            'mood_analysis': mood_analysis,
            'travel_recommendations': travel_recommendations
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mood/analyze-face', methods=['POST'])
def analyze_face_mood():
    try:
        data = request.get_json()
        image_data = data.get('image', '')
        image_url = (data.get('image_url') or '').strip()
        # Force variety and cycling so results differ on every call
        force_variety = True
        force_cycle = True
        if not image_data and image_url:
            # Fetch image from URL and convert to base64 data URL
            import base64
            resp = requests.get(image_url, timeout=10)
            if not resp.ok or not resp.content:
                return jsonify({'error': 'Failed to fetch image from URL'}), 400
            b64 = base64.b64encode(resp.content).decode('utf-8')
            # Default to jpeg container
            image_data = f'data:image/jpeg;base64,{b64}'

        if not image_data:
            return jsonify({'error': 'Image data required'}), 400

        # Attempt analysis with CNN model (prefer_cnn=True ensures CNN is used first)
        fer_result = vision_service.analyze(image_data, force_variety=force_variety, force_cycle=False, prefer_cnn=True)
        def _is_success(res):
            return res and (res.get('status') == 'ok' or res.get('faces_detected', 0) > 0)

        if not _is_success(fer_result):
            try:
                fer_result_cycle = vision_service.analyze(
                    image_data,
                    force_variety=True,
                    force_cycle=True,
                    prefer_cnn=False
                )
            except Exception:
                fer_result_cycle = None
            if _is_success(fer_result_cycle):
                fer_result = fer_result_cycle

        if _is_success(fer_result):
            mood_analysis = {
                'mood': fer_result.get('mood', 'neutral'),
                'confidence': fer_result.get('confidence', 0.5),
                'method': fer_result.get('method', 'cnn_fer'),
                'emotion_label': fer_result.get('emotion_label'),
                'faces_detected': fer_result.get('faces_detected', 0)
            }
        else:
            # Fallback to legacy OpenCV-based heuristic from SimpleAIService
            mood_analysis = legacy_face_service.analyze_face_mood(image_data)
            mood_analysis['method'] = 'cv_fallback'
        
        # Optional: collect in-memory sample from face input (pseudo text)
        try:
            ml_samples.append({'text': f"face:{mood_analysis.get('mood','neutral')}", 'mood': mood_analysis.get('mood','neutral')})
        except Exception:
            pass
        
        # Get recommendations from dataset based on detected mood
        recommendations = []
        if dataset_service:
            try:
                detected_mood = mood_analysis.get('mood', 'neutral')
                recommendations = dataset_service.get_recommendations_from_mood(
                    detected_mood, 
                    n=10,
                    shuffle=True  # Shuffle for variety when same mood repeats
                )
                # Extract just destination data
                recommendations = [rec['destination'] for rec in recommendations]
            except Exception as e:
                print(f"Error getting recommendations: {e}")
        
        # Store mood for the current user if authenticated
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            user_email = user_sessions.get(token)
            if user_email:
                user_moods[user_email] = {
                    'mood': mood_analysis['mood'],
                    'confidence': mood_analysis['confidence'],
                    'timestamp': datetime.now().isoformat(),
                    'method': mood_analysis.get('method', 'face_recognition')
                }
        
        # Persist to DB best-effort (only if ORM models are available)
        if _DB_MODELS_AVAILABLE and DbUserMood is not None:
            try:
                db_mood = DbUserMood(
                    user_id=None,
                    mood_text='[face_input]',
                    mood_type=mood_analysis.get('mood'),
                    intensity=float(mood_analysis.get('confidence', 0) * 10) if isinstance(mood_analysis.get('confidence'), (int, float)) else 5,
                    travel_recommendations=None,
                )
                db.session.add(db_mood)
                db.session.commit()
            except Exception:
                db.session.rollback()

        return jsonify({
            'message': 'Face mood analyzed successfully',
            'mood_analysis': mood_analysis,
            'recommendations': recommendations if recommendations else []
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mood/get-current', methods=['GET'])
def get_current_mood():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
        
        token = auth_header.split(' ')[1]
        user_email = user_sessions.get(token)
        
        if not user_email:
            return jsonify({'error': 'Invalid token'}), 401
        
        current_mood = user_moods.get(user_email, {'mood': 'neutral', 'confidence': 0.5})
        
        return jsonify({
            'current_mood': current_mood
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mood/history', methods=['GET'])
def get_mood_history():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
        
        token = auth_header.split(' ')[1]
        user_email = user_sessions.get(token)
        
        if not user_email:
            return jsonify({'error': 'Invalid token'}), 401
        
        user = users.get(user_email)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'mood_history': user.get('mood_history', [])
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recommendations', methods=['POST'])
def get_recommendations():
    try:
        data = request.get_json()
        mood = data.get('mood', 'neutral')
        user_preferences = data.get('preferences', {})
        n = data.get('n', 10)
        
        # Use dataset service if available
        if dataset_service:
            try:
                recommendations = dataset_service.get_recommendations_from_mood(
                    mood, 
                    n=n,
                    user_preferences=user_preferences,
                    shuffle=True  # Shuffle for variety
                )
                # Format response
                formatted_recs = []
                for rec in recommendations:
                    formatted_recs.append({
                        'destination': rec['destination'],
                        'score': rec['score'],
                        'reasons': [f"Perfect match for your {mood} mood"]
                    })
                
                return jsonify({
                    'recommendations': formatted_recs,
                    'user_mood': mood,
                    'total': len(formatted_recs)
                })
            except Exception as e:
                print(f"Error in dataset recommendations: {e}")
                # Fall through to manual data
        
        # Fallback to manual data
        recommendations = []
        for dest in destinations:
            # Simple mood-based scoring
            score = 0.5  # Base score
            
            if mood == 'happy' and 'relaxation' in dest.get('travel_styles', []):
                score += 0.3
            elif mood == 'relaxed' and 'relaxation' in dest.get('travel_styles', []):
                score += 0.3
            elif mood == 'adventurous' and 'adventure' in dest.get('travel_styles', []):
                score += 0.3
            elif mood == 'romantic' and 'romantic' in dest.get('travel_styles', []):
                score += 0.3
            
            if score > 0.6:
                recommendations.append({
                    'destination': dest,
                    'score': score,
                    'reasons': [f"Perfect for your {mood} mood"]
                })
        
        # Sort by score
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return jsonify({
            'recommendations': recommendations[:n],
            'user_mood': mood,
            'total': len(recommendations)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _build_weather_payload(destination_id: int, destination: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute weather payload for a destination, preferring live OpenWeather data."""
    if destination is None:
        if dataset_service:
            destination = dataset_service.get_destination_by_id(destination_id)
        else:
            destination = None

    if not destination:
        raise ValueError('Destination not found')

    api_key = app.config.get('WEATHER_API_KEY')
    city = (destination.get('city') or destination.get('name') or '').strip()
    country = (destination.get('country') or '').strip()
    coords = destination.get('coordinates') or {}

    def _to_float(value):
        try:
            if value in (None, '', 'NaN', 'nan'):
                return None
            if isinstance(value, str):
                cleaned = value.replace('°', '').replace(',', '').strip()
                if not cleaned:
                    return None
                return float(cleaned)
            return float(value)
        except Exception:
            return None

    lat = _to_float(coords.get('lat'))
    lon = _to_float(coords.get('lng') or coords.get('lon'))

    def build_location_candidates():
        raw_values = [
            destination.get('city'),
            destination.get('name'),
            destination.get('Destination'),
            destination.get('DestinationName'),
            destination.get('region'),
        ]
        candidates = []
        seen = set()

        for value in raw_values:
            if not value:
                continue
            val = str(value).strip()
            if not val:
                continue

            def add_candidate(text):
                normalized = text.strip()
                if normalized and normalized.lower() not in seen:
                    seen.add(normalized.lower())
                    candidates.append(normalized)

            add_candidate(val)

            if '(' in val and ')' in val:
                start = val.find('(')
                end = val.find(')', start + 1)
                if end > start:
                    inside = val[start + 1:end].strip()
                    if inside:
                        add_candidate(inside)

            cleaned = val.replace('-', ' ')
            tokens = [tok for tok in cleaned.split() if tok]
            if len(tokens) >= 2:
                add_candidate(' '.join(tokens[:2]))
            if tokens:
                add_candidate(tokens[0])

        return candidates

    location_candidates = build_location_candidates()

    def call_openweather(api_key_value, *, lat_val=None, lon_val=None, city_val=None, country_val=''):
        base_params = {'appid': api_key_value, 'units': 'metric'}
        query_params = {}
        if lat_val is not None and lon_val is not None:
            query_params = {'lat': lat_val, 'lon': lon_val}
        elif city_val:
            location = f"{city_val},{country_val}".strip(', ')
            query_params = {'q': location}
        else:
            return None

        merged_params = {**base_params, **query_params}
        cur_resp = requests.get('http://api.openweathermap.org/data/2.5/weather', params=merged_params, timeout=10)
        if not cur_resp.ok:
            return None

        fc_resp = requests.get('http://api.openweathermap.org/data/2.5/forecast', params=merged_params, timeout=10)
        fc_json = fc_resp.json() if fc_resp.ok else {}
        return cur_resp.json(), fc_json

    def geocode_city(api_key_value, city_val, country_val=''):
        if not city_val:
            return None, None
        try:
            q = f"{city_val},{country_val}".strip(', ')
            geo_resp = requests.get(
                'http://api.openweathermap.org/geo/1.0/direct',
                params={'q': q, 'limit': 1, 'appid': api_key_value},
                timeout=10
            )
            if geo_resp.ok:
                results = geo_resp.json()
                if results:
                    return results[0].get('lat'), results[0].get('lon')
        except Exception as geo_err:
            print(f"Geocoding error for {city_val},{country_val}: {geo_err}")
        return None, None

    weather_payload = None

    if api_key:
        try:
            if lat is not None and lon is not None:
                weather_payload = call_openweather(api_key, lat_val=lat, lon_val=lon)

            if not weather_payload:
                candidate_list = location_candidates or ([city] if city else [])
                for candidate in candidate_list:
                    if lat is not None and lon is not None:
                        break
                    geo_lat, geo_lon = geocode_city(api_key, candidate, country)
                    geo_lat = _to_float(geo_lat)
                    geo_lon = _to_float(geo_lon)
                    lat = lat or geo_lat
                    lon = lon or geo_lon
                    if lat is not None and lon is not None:
                        weather_payload = call_openweather(api_key, lat_val=lat, lon_val=lon)
                        if weather_payload:
                            break

            if not weather_payload:
                candidate_list = location_candidates or ([city] if city else [])
                for candidate in candidate_list:
                    weather_payload = call_openweather(api_key, city_val=candidate, country_val=country)
                    if weather_payload:
                        break
        except Exception as e:
            print(f"Weather API error for {city},{country}: {e}")
            import traceback
            traceback.print_exc()

    if weather_payload:
        cur_json, fc_json = weather_payload
        main = cur_json.get('main', {})
        weather_info = (cur_json.get('weather') or [{}])[0]
        coord = cur_json.get('coord', {}) or {'lat': lat, 'lon': lon}

        current = {
            'temperature': main.get('temp'),
            'condition': weather_info.get('main', ''),
            'description': weather_info.get('description', ''),
            'humidity': main.get('humidity'),
            'wind_speed': cur_json.get('wind', {}).get('speed', 0),
            'feels_like': main.get('feels_like'),
            'uv_index': None,
        }

        forecast = []
        for item in (fc_json.get('list', []) if isinstance(fc_json, dict) else [])[:7]:
            forecast.append({
                'datetime': item.get('dt_txt', ''),
                'temperature': item.get('main', {}).get('temp'),
                'condition': (item.get('weather') or [{}])[0].get('main', ''),
                'description': (item.get('weather') or [{}])[0].get('description', ''),
                'precipitation': item.get('pop', 0),
                'humidity': item.get('main', {}).get('humidity'),
            })

        return {
            'destination': destination.get('name', ''),
            'country': country,
            'current': current,
            'forecast': forecast,
            'location': {
                'lat': coord.get('lat') if coord else lat,
                'lng': coord.get('lon') if coord else lon,
            },
            'timezone': cur_json.get('timezone', 'UTC'),
            'seasonal_info': {
                'current_season': get_current_season(),
                'best_time_to_visit': destination.get('best_time_to_visit', ''),
                'climate_type': get_climate_type(country),
            },
            'source': 'openweathermap-live',
        }

    avg_temp = destination.get('avg_temperature', {'min': 20, 'max': 25})
    if isinstance(avg_temp, dict):
        temp_max = avg_temp.get('max', 25)
    else:
        temp_max = 25

    return {
        'destination': destination.get('name', ''),
        'country': country,
        'current': {
            'temperature': temp_max,
            'condition': get_weather_condition(country),
            'description': get_weather_description(country),
            'humidity': get_humidity_by_country(country),
            'wind_speed': get_wind_speed_by_country(country),
            'feels_like': temp_max + 2,
            'uv_index': get_uv_index_by_country(country),
        },
        'forecast': generate_weather_forecast(
            country,
            avg_temp if isinstance(avg_temp, dict) else {'min': 20, 'max': 25},
        ),
        'location': {'lat': None, 'lng': None},
        'timezone': 'UTC',
        'seasonal_info': {
            'current_season': get_current_season(),
            'best_time_to_visit': destination.get('best_time_to_visit', ''),
            'climate_type': get_climate_type(country),
        },
        'source': 'static-fallback',
    }


@app.route('/api/weather/<int:destination_id>', methods=['GET'])
def get_weather(destination_id):
    try:
        payload = _build_weather_payload(destination_id)
        return jsonify(payload)
    except ValueError as err:
        return jsonify({'error': str(err)}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def get_weather_condition(country):
    conditions = {
        'India': 'Sunny',
        'Indonesia': 'Partly Cloudy',
        'Switzerland': 'Clear',
        'France': 'Cloudy',
        'Japan': 'Sunny',
        'Greece': 'Sunny',
        'USA': 'Partly Cloudy',
        'Peru': 'Clear',
        'Australia': 'Sunny',
        'Jordan': 'Clear',
        'Iceland': 'Cloudy',
        'Tanzania': 'Sunny',
        'Brazil': 'Partly Cloudy',
        'UAE': 'Sunny',
        'Morocco': 'Clear',
        'Thailand': 'Partly Cloudy'
    }
    return conditions.get(country, 'Sunny')

def get_weather_description(country):
    descriptions = {
        'India': 'clear sky with warm temperatures',
        'Indonesia': 'partly cloudy with tropical humidity',
        'Switzerland': 'clear alpine air',
        'France': 'mild continental weather',
        'Japan': 'sunny with seasonal variations',
        'Greece': 'mediterranean sunshine',
        'USA': 'varied continental climate',
        'Peru': 'clear andean mountain air',
        'Australia': 'sunny australian weather',
        'Jordan': 'clear desert sky',
        'Iceland': 'cool nordic climate',
        'Tanzania': 'tropical african weather',
        'Brazil': 'tropical south american climate',
        'UAE': 'hot desert weather',
        'Morocco': 'mediterranean climate',
        'Thailand': 'tropical southeast asian weather'
    }
    return descriptions.get(country, 'clear sky')

def get_humidity_by_country(country):
    humidity_levels = {
        'India': 70,
        'Indonesia': 80,
        'Switzerland': 60,
        'France': 65,
        'Japan': 75,
        'Greece': 55,
        'USA': 65,
        'Peru': 50,
        'Australia': 60,
        'Jordan': 45,
        'Iceland': 75,
        'Tanzania': 65,
        'Brazil': 75,
        'UAE': 50,
        'Morocco': 55,
        'Thailand': 80
    }
    return humidity_levels.get(country, 65)

def get_wind_speed_by_country(country):
    wind_speeds = {
        'India': 8,
        'Indonesia': 12,
        'Switzerland': 15,
        'France': 10,
        'Japan': 8,
        'Greece': 12,
        'USA': 10,
        'Peru': 6,
        'Australia': 15,
        'Jordan': 8,
        'Iceland': 20,
        'Tanzania': 10,
        'Brazil': 8,
        'UAE': 12,
        'Morocco': 10,
        'Thailand': 8
    }
    return wind_speeds.get(country, 10)

def get_uv_index_by_country(country):
    uv_indices = {
        'India': 8,
        'Indonesia': 9,
        'Switzerland': 6,
        'France': 5,
        'Japan': 7,
        'Greece': 8,
        'USA': 7,
        'Peru': 9,
        'Australia': 10,
        'Jordan': 9,
        'Iceland': 4,
        'Tanzania': 8,
        'Brazil': 9,
        'UAE': 10,
        'Morocco': 8,
        'Thailand': 9
    }
    return uv_indices.get(country, 7)

def generate_weather_forecast(country, avg_temp):
    import random
    base_temp = avg_temp['max']
    forecast = []
    
    for i in range(7):
        temp_variation = random.randint(-5, 5)
        temp = max(avg_temp['min'], min(avg_temp['max'], base_temp + temp_variation))
        
        conditions = ['Sunny', 'Partly Cloudy', 'Cloudy', 'Rainy', 'Clear']
        condition = random.choice(conditions)
        
        forecast.append({
            'datetime': datetime.now(timezone.utc).isoformat(),
            'temperature': temp,
            'condition': condition,
            'precipitation': random.uniform(0, 0.5),
            'humidity': get_humidity_by_country(country) + random.randint(-10, 10)
        })
    
    return forecast

def get_current_season():
    from datetime import datetime
    month = datetime.now().month
    if month in [12, 1, 2]:
        return 'Winter'
    elif month in [3, 4, 5]:
        return 'Spring'
    elif month in [6, 7, 8]:
        return 'Summer'
    else:
        return 'Autumn'

def get_climate_type(country):
    climate_types = {
        'India': 'Tropical and Subtropical',
        'Indonesia': 'Tropical',
        'Switzerland': 'Alpine',
        'France': 'Temperate',
        'Japan': 'Temperate',
        'Greece': 'Mediterranean',
        'USA': 'Varied',
        'Peru': 'Andean',
        'Australia': 'Varied',
        'Jordan': 'Desert',
        'Iceland': 'Subarctic',
        'Tanzania': 'Tropical',
        'Brazil': 'Tropical',
        'UAE': 'Desert',
        'Morocco': 'Mediterranean',
        'Thailand': 'Tropical'
    }
    return climate_types.get(country, 'Temperate')

@app.route('/api/budget/estimate', methods=['POST'])
def estimate_budget():
    try:
        data = request.get_json()
        destination_id = data.get('destination_id')
        duration = data.get('duration', 1)
        group_size = data.get('group_size', 1)
        accommodation_type = data.get('accommodation_type', 'mid')
        
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Enhanced cost calculation with detailed breakdown
        base_multiplier = get_cost_multiplier(destination['cost_level'])
        
        # Accommodation costs with hotel options
        hotels = get_hotels_for_destination(destination['country'], accommodation_type)
        accommodation_cost = calculate_accommodation_cost(hotels, duration, group_size, accommodation_type)
        
        # Food costs
        food_cost = calculate_food_cost(destination['country'], duration, group_size, base_multiplier)
        
        # Transport costs
        transport_cost = calculate_transport_cost(destination['country'], duration, group_size, base_multiplier)
        
        # Activities costs
        activities_cost = calculate_activities_cost(destination['country'], duration, group_size, base_multiplier)
        
        # Additional costs
        visa_cost = get_visa_cost(destination['country'], group_size)
        insurance_cost = get_insurance_cost(duration, group_size)
        
        total_cost = accommodation_cost + food_cost + transport_cost + activities_cost + visa_cost + insurance_cost
        
        return jsonify({
            'destination': destination['name'],
            'duration': duration,
            'group_size': group_size,
            'accommodation': {
                'cost': accommodation_cost,
                'hotels': hotels,
                'type': accommodation_type
            },
            'food': {
                'cost': food_cost,
                'daily_budget': food_cost / (duration * group_size) if duration * group_size > 0 else 0
            },
            'transport': {
                'cost': transport_cost,
                'breakdown': get_transport_breakdown(destination['country'])
            },
            'activities': {
                'cost': activities_cost,
                'suggestions': get_activity_suggestions(destination['country'])
            },
            'additional': {
                'visa': visa_cost,
                'insurance': insurance_cost
            },
            'total': total_cost,
            'per_person': total_cost / group_size if group_size > 0 else 0,
        })  # Close the JSON response here
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/budget/country/<country_name>', methods=['GET'])
def get_country_budget(country_name):
    try:
        # Find destination for the country
        destination = next((d for d in destinations if d['country'].lower() == country_name.lower()), None)
        
        if not destination:
            # Fallback: synthesize a destination with sensible defaults
            destination = {
                'country': country_name.title(),
                'currency': 'USD',
                'cost_level': 'moderate'
            }
        
        # Get budget for different accommodation types
        budget_data = {
            'country': destination['country'],
            'currency': destination['currency'],
            'cost_level': destination['cost_level'],
            'budgets': {}
        }
        
        for acc_type in ['budget', 'mid', 'luxury']:
            budget_data['budgets'][acc_type] = calculate_country_budget(destination, 7, 2, acc_type)
        
        return jsonify(budget_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/budget/comparison', methods=['GET'])
def get_budget_comparison():
    try:
        countries = request.args.getlist('countries')
        duration = int(request.args.get('duration', 7))
        group_size = int(request.args.get('group_size', 2))
        accommodation_type = request.args.get('accommodation_type', 'mid')
        
        comparison_data = []
        
        for country in countries:
            destination = next((d for d in destinations if d['country'].lower() == country.lower()), None)
            if destination:
                budget = calculate_country_budget(destination, duration, group_size, accommodation_type)
                comparison_data.append({
                    'country': destination['country'],
                    'total_budget': budget['total'],
                    'per_person': budget['per_person'],
                    'currency': destination['currency'],
                    'cost_level': destination['cost_level']
                })
        
        return jsonify({
            'comparison': comparison_data,
            'duration': duration,
            'group_size': group_size,
            'accommodation_type': accommodation_type
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def calculate_country_budget(destination, duration, group_size, accommodation_type):
    import random
    from datetime import datetime
    
    # Add dynamic pricing with seasonal variations
    current_month = datetime.now().month
    
    # Seasonal multipliers
    seasonal_multipliers = {
        'summer': 1.2 if current_month in [6, 7, 8] else 1.0,
        'winter': 0.8 if current_month in [12, 1, 2] else 1.0,
        'spring': 1.1 if current_month in [3, 4, 5] else 1.0,
        'autumn': 1.0 if current_month in [9, 10, 11] else 1.0
    }
    
    # Dynamic pricing with random variations
    def get_dynamic_price(base_price):
        variation = random.uniform(0.9, 1.3)  # ±30% variation
        return round(base_price * variation, 2)
    
    base_multiplier = get_cost_multiplier(destination['cost_level'])
    
    # Apply seasonal and dynamic pricing
    seasonal_multiplier = seasonal_multipliers.get('summer', 1.0)  # Default to summer
    dynamic_multiplier = random.uniform(0.95, 1.15)  # ±15% daily variation
    
    # Accommodation costs with dynamic pricing
    hotels = get_hotels_for_destination(destination['country'], accommodation_type)
    accommodation_cost = calculate_accommodation_cost(hotels, duration, group_size, accommodation_type)
    accommodation_cost = accommodation_cost * seasonal_multiplier * dynamic_multiplier
    
    # Food costs with dynamic pricing
    food_cost = calculate_food_cost(destination['country'], duration, group_size, base_multiplier)
    food_cost = food_cost * seasonal_multiplier * dynamic_multiplier
    
    # Transport costs with dynamic pricing
    transport_cost = calculate_transport_cost(destination['country'], duration, group_size, base_multiplier)
    transport_cost = transport_cost * seasonal_multiplier * dynamic_multiplier
    
    # Activities costs with dynamic pricing
    activities_cost = calculate_activities_cost(destination['country'], duration, group_size, base_multiplier)
    activities_cost = activities_cost * seasonal_multiplier * dynamic_multiplier
    
    # Additional costs
    visa_cost = get_visa_cost(destination['country'], group_size)
    insurance_cost = get_insurance_cost(duration, group_size)
    
    total_cost = accommodation_cost + food_cost + transport_cost + activities_cost + visa_cost + insurance_cost
    
    return {
        'accommodation': round(accommodation_cost, 2),
        'food': round(food_cost, 2),
        'transport': round(transport_cost, 2),
        'activities': round(activities_cost, 2),
        'additional': round(visa_cost + insurance_cost, 2),
        'total': round(total_cost, 2),
        'per_person': round(total_cost / group_size, 2) if group_size > 0 else 0,
        'seasonal_multiplier': round(seasonal_multiplier, 2),
        'dynamic_multiplier': round(dynamic_multiplier, 2),
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def get_cost_multiplier(cost_level):
    multipliers = {
        'expensive': 1.8,
        'moderate': 1.0,
        'budget': 0.6
    }
    return multipliers.get(cost_level, 1.0)

def get_hotels_for_destination(country, accommodation_type):
    hotels = {
        'India': {
            'budget': [
                {'name': 'OYO Rooms', 'price': 25, 'rating': 3.5, 'amenities': ['WiFi', 'AC']},
                {'name': 'Hotel Comfort', 'price': 35, 'rating': 3.8, 'amenities': ['WiFi', 'AC', 'Restaurant']}
            ],
            'mid': [
                {'name': 'Taj Hotels', 'price': 80, 'rating': 4.2, 'amenities': ['WiFi', 'AC', 'Pool', 'Spa']},
                {'name': 'ITC Hotels', 'price': 95, 'rating': 4.4, 'amenities': ['WiFi', 'AC', 'Pool', 'Gym']}
            ],
            'luxury': [
                {'name': 'The Oberoi', 'price': 200, 'rating': 4.8, 'amenities': ['WiFi', 'AC', 'Pool', 'Spa', 'Butler']},
                {'name': 'The Leela Palace', 'price': 250, 'rating': 4.9, 'amenities': ['WiFi', 'AC', 'Pool', 'Spa', 'Butler', 'Helipad']}
            ]
        },
        'Switzerland': {
            'budget': [
                {'name': 'Swiss Youth Hostel', 'price': 45, 'rating': 3.2, 'amenities': ['WiFi', 'Kitchen']},
                {'name': 'Hotel Alpenblick', 'price': 65, 'rating': 3.6, 'amenities': ['WiFi', 'Restaurant']}
            ],
            'mid': [
                {'name': 'Hotel Schweizerhof', 'price': 150, 'rating': 4.1, 'amenities': ['WiFi', 'Spa', 'Restaurant']},
                {'name': 'Hotel Bellevue', 'price': 180, 'rating': 4.3, 'amenities': ['WiFi', 'Pool', 'Spa']}
            ],
            'luxury': [
                {'name': 'Badrutt\'s Palace', 'price': 400, 'rating': 4.9, 'amenities': ['WiFi', 'Pool', 'Spa', 'Butler', 'Skiing']},
                {'name': 'The Dolder Grand', 'price': 500, 'rating': 4.9, 'amenities': ['WiFi', 'Pool', 'Spa', 'Butler', 'Golf']}
            ]
        },
        'France': {
            'budget': [
                {'name': 'Ibis Budget', 'price': 40, 'rating': 3.1, 'amenities': ['WiFi', 'Breakfast']},
                {'name': 'Hotel Formule 1', 'price': 50, 'rating': 3.3, 'amenities': ['WiFi', 'Parking']}
            ],
            'mid': [
                {'name': 'Mercure Hotels', 'price': 120, 'rating': 4.0, 'amenities': ['WiFi', 'Restaurant', 'Bar']},
                {'name': 'Novotel', 'price': 140, 'rating': 4.1, 'amenities': ['WiFi', 'Pool', 'Restaurant']}
            ],
            'luxury': [
                {'name': 'Ritz Paris', 'price': 800, 'rating': 4.9, 'amenities': ['WiFi', 'Pool', 'Spa', 'Butler', 'Michelin Restaurant']},
                {'name': 'Four Seasons George V', 'price': 1000, 'rating': 4.9, 'amenities': ['WiFi', 'Pool', 'Spa', 'Butler', 'Wine Cellar']}
            ]
        }
    }
    
    # Default hotels for other countries
    default_hotels = {
        'budget': [
            {'name': 'Local Budget Hotel', 'price': 30, 'rating': 3.0, 'amenities': ['WiFi']},
            {'name': 'Hostel International', 'price': 25, 'rating': 3.2, 'amenities': ['WiFi', 'Kitchen']}
        ],
        'mid': [
            {'name': 'Comfort Inn', 'price': 80, 'rating': 3.8, 'amenities': ['WiFi', 'Breakfast']},
            {'name': 'Holiday Inn Express', 'price': 90, 'rating': 3.9, 'amenities': ['WiFi', 'Pool']}
        ],
        'luxury': [
            {'name': 'Grand Hotel', 'price': 200, 'rating': 4.5, 'amenities': ['WiFi', 'Pool', 'Spa']},
            {'name': 'Luxury Resort', 'price': 300, 'rating': 4.7, 'amenities': ['WiFi', 'Pool', 'Spa', 'Butler']}
        ]
    }
    
    return hotels.get(country, default_hotels).get(accommodation_type, default_hotels['mid'])

def calculate_accommodation_cost(hotels, duration, group_size, accommodation_type):
    if not hotels:
        return 80 * duration * group_size
    
    avg_price = sum(hotel['price'] for hotel in hotels) / len(hotels)
    return avg_price * duration * group_size

def calculate_food_cost(country, duration, group_size, base_multiplier):
    food_costs = {
        'India': 15,
        'Switzerland': 40,
        'France': 35,
        'Japan': 30,
        'Greece': 25,
        'USA': 35,
        'Peru': 20,
        'Australia': 40,
        'Jordan': 25,
        'Iceland': 45,
        'Tanzania': 20,
        'Brazil': 25,
        'UAE': 35,
        'Morocco': 20,
        'Thailand': 15
    }
    
    daily_food_cost = food_costs.get(country, 25)
    return daily_food_cost * duration * group_size * 3 * base_multiplier  # 3 meals per day

def calculate_transport_cost(country, duration, group_size, base_multiplier):
    transport_costs = {
        'India': 10,
        'Switzerland': 25,
        'France': 20,
        'Japan': 15,
        'Greece': 15,
        'USA': 20,
        'Peru': 12,
        'Australia': 25,
        'Jordan': 15,
        'Iceland': 30,
        'Tanzania': 12,
        'Brazil': 15,
        'UAE': 20,
        'Morocco': 12,
        'Thailand': 10
    }
    
    daily_transport_cost = transport_costs.get(country, 15)
    return daily_transport_cost * duration * group_size * base_multiplier

def calculate_activities_cost(country, duration, group_size, base_multiplier):
    activity_costs = {
        'India': 20,
        'Switzerland': 50,
        'France': 40,
        'Japan': 35,
        'Greece': 30,
        'USA': 40,
        'Peru': 25,
        'Australia': 45,
        'Jordan': 30,
        'Iceland': 60,
        'Tanzania': 35,
        'Brazil': 30,
        'UAE': 40,
        'Morocco': 25,
        'Thailand': 20
    }
    
    daily_activity_cost = activity_costs.get(country, 30)
    return daily_activity_cost * duration * group_size * base_multiplier

def get_visa_cost(country, group_size):
    visa_costs = {
        'India': 0,  # Many countries have visa-free or e-visa
        'Switzerland': 0,  # Schengen visa
        'France': 0,  # Schengen visa
        'Japan': 0,  # Many countries have visa-free access
        'Greece': 0,  # Schengen visa
        'USA': 160,
        'Peru': 0,
        'Australia': 0,
        'Jordan': 40,
        'Iceland': 0,  # Schengen visa
        'Tanzania': 50,
        'Brazil': 0,
        'UAE': 0,
        'Morocco': 0,
        'Thailand': 0
    }
    
    return visa_costs.get(country, 0) * group_size

def get_insurance_cost(duration, group_size):
    # Travel insurance: approximately $5-10 per day per person
    daily_insurance_cost = 7
    return daily_insurance_cost * duration * group_size

def get_transport_breakdown(country):
    breakdowns = {
        'India': {'local_transport': 5, 'intercity': 15, 'airport_transfer': 10},
        'Switzerland': {'local_transport': 15, 'intercity': 30, 'airport_transfer': 25},
        'France': {'local_transport': 12, 'intercity': 25, 'airport_transfer': 20},
        'Japan': {'local_transport': 8, 'intercity': 20, 'airport_transfer': 15},
        'Greece': {'local_transport': 8, 'intercity': 18, 'airport_transfer': 12},
        'USA': {'local_transport': 15, 'intercity': 25, 'airport_transfer': 20},
        'Peru': {'local_transport': 6, 'intercity': 15, 'airport_transfer': 10},
        'Australia': {'local_transport': 18, 'intercity': 30, 'airport_transfer': 25},
        'Jordan': {'local_transport': 8, 'intercity': 18, 'airport_transfer': 12},
        'Iceland': {'local_transport': 20, 'intercity': 35, 'airport_transfer': 30},
        'Tanzania': {'local_transport': 6, 'intercity': 15, 'airport_transfer': 10},
        'Brazil': {'local_transport': 8, 'intercity': 18, 'airport_transfer': 12},
        'UAE': {'local_transport': 12, 'intercity': 25, 'airport_transfer': 20},
        'Morocco': {'local_transport': 6, 'intercity': 15, 'airport_transfer': 10},
        'Thailand': {'local_transport': 5, 'intercity': 12, 'airport_transfer': 8}
    }
    return breakdowns.get(country, {'local_transport': 10, 'intercity': 20, 'airport_transfer': 15})

def get_activity_suggestions(country):
    suggestions = {
        'India': ['Temple visits', 'Yoga classes', 'Spice market tours', 'Boat rides'],
        'Switzerland': ['Skiing', 'Hiking', 'Cable car rides', 'Chocolate factory tours'],
        'France': ['Wine tasting', 'Museum visits', 'Eiffel Tower', 'Seine River cruise'],
        'Japan': ['Temple visits', 'Sushi making', 'Cherry blossom viewing', 'Onsen baths'],
        'Greece': ['Island hopping', 'Ancient ruins', 'Wine tasting', 'Beach activities'],
        'USA': ['Theme parks', 'National parks', 'City tours', 'Shopping'],
        'Peru': ['Machu Picchu trek', 'Amazon jungle', 'Lima food tours', 'Sacred Valley'],
        'Australia': ['Great Barrier Reef', 'Sydney Opera House', 'Outback tours', 'Beach activities'],
        'Jordan': ['Petra exploration', 'Wadi Rum desert', 'Dead Sea', 'Amman city tour'],
        'Iceland': ['Northern Lights', 'Blue Lagoon', 'Golden Circle', 'Glacier hiking'],
        'Tanzania': ['Safari tours', 'Zanzibar beaches', 'Kilimanjaro trek', 'Cultural tours'],
        'Brazil': ['Carnival', 'Amazon tours', 'Beach activities', 'Christ the Redeemer'],
        'UAE': ['Desert safari', 'Burj Khalifa', 'Shopping malls', 'Palm Jumeirah'],
        'Morocco': ['Sahara desert', 'Medina tours', 'Atlas Mountains', 'Coastal towns'],
        'Thailand': ['Temple visits', 'Island hopping', 'Thai cooking', 'Elephant sanctuaries']
    }
    return suggestions.get(country, ['Local tours', 'Cultural activities', 'Adventure sports', 'Food experiences'])

@app.route('/api/packing/generate', methods=['POST'])
def generate_packing_list():
    try:
        data = request.get_json()
        country = data.get('country')
        activities = data.get('activities', [])
        duration = data.get('duration', 7)
        season = data.get('season', 'summer')
        
        if not country:
            return jsonify({'error': 'Country is required'}), 400
        
        # Enhanced country-specific packing list
        packing_list = generate_country_specific_packing_list(
            country, 
            25,  # Default temperature
            ', '.join(activities) if activities else 'general', 
            duration, 
            season
        )
        
        return jsonify({
            'country': country,
            'duration': duration,
            'season': season,
            'packing_list': packing_list,
            'special_notes': get_packing_notes(country)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_country_specific_packing_list(country, temperature, activities, duration, season):
    base_items = {
        'essentials': [
            'Passport and travel documents',
            'Travel insurance documents',
            'Credit/debit cards and cash',
            'Phone and charger',
            'Power bank (20,000mAh)',
            'Universal adapter',
            'Emergency contact information',
            'Copies of important documents',
            'Travel itinerary',
            'Hotel confirmations',
            'Flight tickets',
            'Visa documents',
            'International driving permit (if driving)',
            'Travel wallet/money belt',
            'Luggage tags',
            'Luggage locks',
            'Travel pillow',
            'Eye mask and earplugs',
            'Travel blanket',
            'Water bottle (reusable)',
            'Snacks for travel',
            'Books/magazines',
            'Travel journal and pen',
            'Small umbrella',
            'Ziploc bags (various sizes)',
            'Duct tape (small roll)',
            'Safety pins',
            'Rubber bands'
        ],
        'documents': [
            'Flight tickets',
            'Hotel reservations',
            'Vaccination records',
            'Travel itinerary',
            'Car rental confirmation',
            'Tour bookings',
            'Restaurant reservations',
            'Event tickets',
            'Travel insurance policy',
            'Medical records',
            'Prescription information',
            'Emergency contact list',
            'Local embassy contacts',
            'Travel apps downloaded'
        ],
        'electronics': [
            'Phone and charger',
            'Camera and memory cards',
            'Camera charger',
            'Laptop/tablet (if needed)',
            'Laptop charger',
            'Power bank (20,000mAh)',
            'Universal adapter',
            'Headphones/earbuds',
            'Portable speaker (optional)',
            'GoPro (if adventure activities)',
            'GoPro accessories',
            'Tripod (collapsible)',
            'Selfie stick',
            'USB cables',
            'SD card reader',
            'Portable hard drive',
            'Bluetooth speaker',
            'E-reader (optional)',
            'Smartwatch and charger',
            'Drone (if allowed)',
            'Drone batteries',
            'Extension cord',
            'Multi-port USB charger'
        ],
        'toiletries': [
            'Toothbrush and toothpaste',
            'Dental floss',
            'Mouthwash',
            'Shampoo and conditioner',
            'Soap or body wash',
            'Body lotion',
            'Deodorant',
            'Hairbrush/comb',
            'Hair ties and clips',
            'Razor and shaving cream',
            'Nail clippers and file',
            'Tweezers',
            'Cotton swabs',
            'Cotton balls',
            'Sunscreen (SPF 30+)',
            'Lip balm with SPF',
            'Hand sanitizer',
            'Wet wipes',
            'Tissues',
            'Feminine hygiene products',
            'Contact lenses and solution',
            'Glasses and case',
            'Makeup and makeup remover',
            'Perfume/cologne',
            'Hair styling products',
            'Hair dryer (if needed)',
            'Curling iron/straightener (if needed)',
            'Mirror (compact)',
            'Towel (quick-dry)',
            'Washcloth',
            'Toilet paper (small roll)',
            'Air freshener',
            'Laundry detergent (travel size)',
            'Stain remover pen'
        ],
        'health_and_safety': [
            'First aid kit',
            'Prescription medications',
            'Pain relievers (Ibuprofen, Acetaminophen)',
            'Motion sickness medication',
            'Anti-diarrhea medication',
            'Antihistamines',
            'Cough drops',
            'Vitamins',
            'Insect repellent',
            'Band-aids (various sizes)',
            'Antiseptic wipes',
            'Thermometer',
            'Face masks (10-15)',
            'Hand sanitizer',
            'Disposable gloves',
            'Eye drops',
            'Nasal spray',
            'Sleeping pills (if needed)',
            'Anti-anxiety medication (if needed)',
            'Allergy medication',
            'Pepto-Bismol',
            'Laxatives',
            'Antacids',
            'Cough syrup',
            'Cold medicine',
            'Emergency contact list',
            'Medical insurance card',
            'Blood type information',
            'Allergy information card'
        ]
    }
    
    # Country-specific clothing
    clothing = get_country_clothing(country, temperature, season)
    
    # Activity-specific items
    activity_items = get_activity_items(activities)
    
    # Country-specific items
    country_specific = get_country_specific_items(country)
    
    # Calculate quantities based on duration
    quantities = calculate_quantities(duration)
    
    # Add comprehensive packing categories
    comprehensive_packing = {
        'essentials': base_items['essentials'],
        'documents': base_items['documents'],
        'electronics': base_items['electronics'],
        'toiletries': base_items['toiletries'],
        'health_and_safety': base_items['health_and_safety'],
        'clothing': clothing,
        'activity_specific': activity_items,
        'country_specific': country_specific,
        'quantities': quantities,
        'seasonal_items': get_seasonal_items(season, country),
        'special_equipment': get_special_equipment(activities, country),
        'entertainment': [
            'Books or e-reader',
            'Travel journal and pens',
            'Playing cards or board games',
            'Music player with headphones',
            'Language learning app',
            'Travel guidebooks',
            'Crossword puzzles or sudoku',
            'Sketchbook and pencils (if artistic)',
            'Portable speaker',
            'Camera accessories'
        ],
        'comfort_items': [
            'Travel pillow and blanket',
            'Eye mask and earplugs',
            'Compression socks for long flights',
            'Hand lotion and lip balm',
            'Travel-sized humidifier',
            'Portable fan',
            'Heating pad or hot water bottle',
            'Comfortable slippers',
            'Travel yoga mat',
            'Massage ball or foam roller'
        ],
        'organization': [
            'Packing cubes or compression bags',
            'Travel wallet or money belt',
            'Ziploc bags in various sizes',
            'Travel-sized laundry detergent',
            'Clothes hangers (collapsible)',
            'Shoe bags',
            'Jewelry organizer',
            'Cable organizer',
            'Travel-sized sewing kit',
            'Mini stapler and paper clips'
        ],
        'emergency_preparedness': [
            'Emergency contact list',
            'Copies of important documents',
            'Travel insurance information',
            'Local emergency numbers',
            'First aid kit',
            'Emergency cash in different currencies',
            'Portable charger',
            'Flashlight or headlamp',
            'Whistle for emergencies',
            'Emergency blanket'
        ]
    }
    
    return comprehensive_packing

def get_country_clothing(country, temperature, season):
    clothing_items = {
        'India': {
            'summer': ['Light cotton clothes', 'Saree/Kurta (for cultural visits)', 'Comfortable sandals', 'Hat', 'Sunglasses'],
            'winter': ['Light sweater', 'Jacket', 'Warm socks', 'Comfortable shoes'],
            'monsoon': ['Raincoat', 'Umbrella', 'Waterproof shoes', 'Quick-dry clothes']
        },
        'Switzerland': {
            'summer': ['Light layers', 'Hiking boots', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Heavy winter coat', 'Thermal underwear', 'Warm gloves', 'Scarf', 'Winter boots'],
            'spring': ['Light jacket', 'Comfortable walking shoes', 'Layers', 'Rain jacket'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Gloves']
        },
        'France': {
            'summer': ['Light clothes', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Warm coat', 'Scarf', 'Gloves', 'Warm shoes', 'Layers'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Umbrella'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'Japan': {
            'summer': ['Light clothes', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Warm coat', 'Thermal underwear', 'Gloves', 'Warm shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Umbrella'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'Greece': {
            'summer': ['Light clothes', 'Swimwear', 'Beach towel', 'Sunglasses', 'Hat', 'Comfortable sandals'],
            'winter': ['Light jacket', 'Warm layers', 'Comfortable shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Swimwear'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'USA': {
            'summer': ['Light clothes', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Warm coat', 'Thermal underwear', 'Gloves', 'Warm shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Umbrella'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'Peru': {
            'summer': ['Light clothes', 'Hiking boots', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Warm layers', 'Hiking boots', 'Gloves', 'Warm jacket', 'Thermal underwear'],
            'spring': ['Light jacket', 'Hiking boots', 'Layers', 'Rain jacket'],
            'autumn': ['Medium jacket', 'Warm layers', 'Hiking boots', 'Gloves']
        },
        'Australia': {
            'summer': ['Light clothes', 'Swimwear', 'Beach towel', 'Sunglasses', 'Hat', 'Comfortable sandals'],
            'winter': ['Light jacket', 'Warm layers', 'Comfortable shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Swimwear'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'Jordan': {
            'summer': ['Light clothes', 'Modest clothing', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Scarf'],
            'winter': ['Warm layers', 'Modest clothing', 'Comfortable shoes', 'Warm jacket', 'Gloves'],
            'spring': ['Light jacket', 'Modest clothing', 'Comfortable shoes', 'Layers'],
            'autumn': ['Medium jacket', 'Modest clothing', 'Warm layers', 'Comfortable shoes']
        },
        'Iceland': {
            'summer': ['Warm layers', 'Waterproof jacket', 'Hiking boots', 'Gloves', 'Hat', 'Thermal underwear'],
            'winter': ['Heavy winter coat', 'Thermal underwear', 'Warm gloves', 'Winter boots', 'Scarf', 'Warm hat'],
            'spring': ['Warm layers', 'Waterproof jacket', 'Hiking boots', 'Gloves', 'Hat'],
            'autumn': ['Warm layers', 'Waterproof jacket', 'Hiking boots', 'Gloves', 'Hat']
        },
        'Tanzania': {
            'summer': ['Light clothes', 'Neutral colors', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Light jacket', 'Warm layers', 'Comfortable shoes', 'Neutral colors'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Neutral colors'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Neutral colors']
        },
        'Brazil': {
            'summer': ['Light clothes', 'Swimwear', 'Beach towel', 'Sunglasses', 'Hat', 'Comfortable sandals'],
            'winter': ['Light jacket', 'Warm layers', 'Comfortable shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Swimwear'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        },
        'UAE': {
            'summer': ['Light clothes', 'Modest clothing', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Light jacket', 'Modest clothing', 'Comfortable shoes', 'Warm layers', 'Scarf'],
            'spring': ['Light jacket', 'Modest clothing', 'Comfortable shoes', 'Layers'],
            'autumn': ['Medium jacket', 'Modest clothing', 'Warm layers', 'Comfortable shoes']
        },
        'Morocco': {
            'summer': ['Light clothes', 'Modest clothing', 'Comfortable walking shoes', 'Sunglasses', 'Hat', 'Light jacket'],
            'winter': ['Warm layers', 'Modest clothing', 'Comfortable shoes', 'Warm jacket', 'Gloves'],
            'spring': ['Light jacket', 'Modest clothing', 'Comfortable shoes', 'Layers'],
            'autumn': ['Medium jacket', 'Modest clothing', 'Warm layers', 'Comfortable shoes']
        },
        'Thailand': {
            'summer': ['Light clothes', 'Swimwear', 'Beach towel', 'Sunglasses', 'Hat', 'Comfortable sandals'],
            'winter': ['Light jacket', 'Warm layers', 'Comfortable shoes', 'Scarf'],
            'spring': ['Light jacket', 'Comfortable shoes', 'Layers', 'Swimwear'],
            'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes', 'Scarf']
        }
    }
    
    return clothing_items.get(country, {
        'summer': ['Light clothes', 'Comfortable walking shoes', 'Sunglasses', 'Hat'],
        'winter': ['Warm coat', 'Gloves', 'Warm shoes', 'Scarf'],
        'spring': ['Light jacket', 'Comfortable shoes', 'Layers'],
        'autumn': ['Medium jacket', 'Warm layers', 'Comfortable shoes']
    }).get(season.lower(), ['Light clothes', 'Comfortable walking shoes', 'Layers'])

def get_activity_items(activities):
    activity_items = {
        'hiking': ['Hiking boots', 'Backpack', 'Water bottle', 'Energy bars', 'First aid kit', 'Map', 'Compass'],
        'swimming': ['Swimwear', 'Beach towel', 'Sunscreen', 'Beach bag', 'Water shoes'],
        'skiing': ['Ski jacket', 'Ski pants', 'Ski gloves', 'Ski goggles', 'Thermal underwear', 'Ski socks'],
        'safari': ['Neutral colored clothes', 'Binoculars', 'Camera with zoom lens', 'Hat', 'Sunglasses', 'Comfortable walking shoes'],
        'beach': ['Swimwear', 'Beach towel', 'Sunscreen', 'Beach umbrella', 'Beach bag', 'Water shoes'],
        'cultural': ['Modest clothing', 'Comfortable walking shoes', 'Camera', 'Guidebook', 'Respectful attire'],
        'adventure': ['Comfortable athletic wear', 'Hiking boots', 'Backpack', 'Water bottle', 'First aid kit'],
        'luxury': ['Formal wear', 'Dress shoes', 'Accessories', 'Camera', 'Travel documents'],
        'photography': ['Camera and lenses', 'Tripod', 'Memory cards', 'Camera bag', 'Lens cleaning kit', 'Extra batteries'],
        'cycling': ['Bicycle helmet', 'Cycling shorts', 'Cycling shoes', 'Water bottles', 'Bike lock', 'Bike pump'],
        'city': ['Comfortable walking shoes', 'City map', 'Public transport card', 'Camera', 'Comfortable clothes'],
        'general': ['Comfortable walking shoes', 'Camera', 'Travel documents', 'Basic toiletries']
    }
    
    items = []
    # Handle both string and list inputs
    if isinstance(activities, str):
        activity_list = [act.strip() for act in activities.split(',')]
    else:
        activity_list = activities
    
    for activity in activity_list:
        if isinstance(activity, dict) and activity.get('type') in activity_items:
            items.extend(activity_items[activity['type']])
        elif isinstance(activity, str) and activity in activity_items:
            items.extend(activity_items[activity])
    
    return list(set(items))  # Remove duplicates

def get_country_specific_items(country):
    country_items = {
        'India': ['Mosquito repellent', 'Hand sanitizer', 'Modest clothing', 'Temple-appropriate attire', 'Spice tolerance'],
        'Switzerland': ['Swiss army knife', 'Hiking gear', 'Ski equipment (if skiing)', 'Mountain gear', 'Cash (many places don\'t accept cards)'],
        'France': ['French phrasebook', 'Wine opener', 'Museum pass', 'Comfortable walking shoes', 'Umbrella'],
        'Japan': ['Japanese phrasebook', 'Onsen towel', 'Comfortable walking shoes', 'Cash (many places cash-only)', 'Pocket WiFi'],
        'Greece': ['Beach gear', 'Comfortable walking shoes', 'Greek phrasebook', 'Cash', 'Sunscreen'],
        'USA': ['Comfortable walking shoes', 'Credit cards', 'ID', 'Camera', 'Travel documents'],
        'Peru': ['Altitude sickness medication', 'Hiking gear', 'Spanish phrasebook', 'Cash', 'Comfortable walking shoes'],
        'Australia': ['Beach gear', 'Sunscreen', 'Comfortable walking shoes', 'Camera', 'Travel documents'],
        'Jordan': ['Modest clothing', 'Comfortable walking shoes', 'Arabic phrasebook', 'Cash', 'Respectful attire'],
        'Iceland': ['Warm clothing', 'Waterproof gear', 'Hiking boots', 'Camera', 'Cash'],
        'Tanzania': ['Neutral colored clothes', 'Safari gear', 'Camera with zoom lens', 'Cash', 'Comfortable walking shoes'],
        'Brazil': ['Beach gear', 'Portuguese phrasebook', 'Comfortable walking shoes', 'Cash', 'Camera'],
        'UAE': ['Modest clothing', 'Comfortable walking shoes', 'Arabic phrasebook', 'Cash', 'Respectful attire'],
        'Morocco': ['Modest clothing', 'Comfortable walking shoes', 'Arabic/French phrasebook', 'Cash', 'Respectful attire'],
        'Thailand': ['Beach gear', 'Thai phrasebook', 'Comfortable walking shoes', 'Cash', 'Sunscreen']
    }
    
    return country_items.get(country, ['Comfortable walking shoes', 'Camera', 'Cash', 'Travel documents'])

def calculate_quantities(duration):
    return {
        'underwear': duration + 2,
        'socks': duration + 2,
        't_shirts': duration + 1,
        'pants': min(duration // 2 + 1, 3),
        'toiletries': 1,  # Will refill as needed
        'medications': duration + 3  # Extra buffer
    }

def get_seasonal_items(season, country):
    # Get seasonal items based on season and country
    seasonal_items = {
        'summer': [
            'Lightweight clothing',
            'Sunscreen (SPF 50+)',
            'Sunglasses and hat',
            'Swimwear and beach towel',
            'Insect repellent',
            'Light rain jacket',
            'Comfortable sandals',
            'Portable fan',
            'Cooling towel',
            'Aloe vera gel'
        ],
        'winter': [
            'Warm winter coat',
            'Thermal underwear',
            'Warm gloves and scarf',
            'Winter boots',
            'Warm socks',
            'Hand warmers',
            'Winter hat',
            'Heavy sweater',
            'Warm pajamas',
            'Hot water bottle'
        ],
        'spring': [
            'Light jacket',
            'Umbrella',
            'Light layers',
            'Comfortable walking shoes',
            'Light scarf',
            'Rain boots',
            'Spring clothing',
            'Allergy medication',
            'Light sweater',
            'Waterproof jacket'
        ],
        'autumn': [
            'Medium jacket',
            'Warm layers',
            'Comfortable shoes',
            'Scarf and gloves',
            'Warm socks',
            'Autumn clothing',
            'Light rain jacket',
            'Warm sweater',
            'Comfortable boots',
            'Warm hat'
        ]
    }
    
    return seasonal_items.get(season, [])

def get_special_equipment(activities, country):
    # Get special equipment based on activities and country
    equipment = []
    
    if 'hiking' in activities or 'trekking' in activities:
        equipment.extend([
            'Hiking boots',
            'Hiking poles',
            'Backpack (30-50L)',
            'Water bottles',
            'Hiking socks',
            'Quick-dry clothing',
            'Rain gear',
            'Map and compass',
            'Headlamp',
            'Emergency whistle'
        ])
    
    if 'swimming' in activities or 'beach' in activities:
        equipment.extend([
            'Swimwear',
            'Beach towel',
            'Beach umbrella',
            'Snorkeling gear',
            'Water shoes',
            'Beach bag',
            'Sunscreen',
            'Beach mat',
            'Cooler bag',
            'Beach games'
        ])
    
    if 'photography' in activities:
        equipment.extend([
            'Camera and lenses',
            'Tripod',
            'Memory cards',
            'Camera bag',
            'Lens cleaning kit',
            'Extra batteries',
            'Camera charger',
            'Polarizing filter',
            'Remote shutter',
            'Camera strap'
        ])
    
    if 'skiing' in activities or 'snowboarding' in activities:
        equipment.extend([
            'Ski jacket and pants',
            'Ski boots',
            'Ski goggles',
            'Ski gloves',
            'Thermal underwear',
            'Ski socks',
            'Helmet',
            'Ski poles',
            'Hand warmers',
            'Ski pass'
        ])
    
    if 'cycling' in activities:
        equipment.extend([
            'Bicycle helmet',
            'Cycling shorts',
            'Cycling shoes',
            'Water bottles',
            'Bike lock',
            'Bike pump',
            'Spare tubes',
            'Cycling gloves',
            'Bike lights',
            'Cycling jersey'
        ])
    
    return equipment

def get_packing_notes(country):
    notes = {
        'India': 'Pack light cotton clothes for hot weather. Include modest clothing for temple visits. Carry hand sanitizer and mosquito repellent.',
        'Switzerland': 'Pack layers for changing mountain weather. Include hiking gear if planning outdoor activities. Many places prefer cash payments.',
        'France': 'Pack comfortable walking shoes for city exploration. Include an umbrella for unpredictable weather. Dress stylishly for upscale venues.',
        'Japan': 'Pack comfortable walking shoes for extensive walking. Include cash as many places don\'t accept cards. Respect local customs and dress modestly.',
        'Greece': 'Pack beach gear for island visits. Include comfortable walking shoes for ancient ruins. Carry cash for smaller establishments.',
        'USA': 'Pack comfortable walking shoes for city exploration. Include credit cards as most places accept them. Carry ID at all times.',
        'Peru': 'Pack for altitude changes. Include hiking gear for Machu Picchu. Carry altitude sickness medication and comfortable walking shoes.',
        'Australia': 'Pack beach gear for coastal visits. Include strong sunscreen and comfortable walking shoes. Be prepared for varied weather.',
        'Jordan': 'Pack modest clothing for cultural respect. Include comfortable walking shoes for Petra exploration. Carry cash for local markets.',
        'Iceland': 'Pack warm, waterproof clothing regardless of season. Include hiking boots for outdoor activities. Be prepared for changing weather.',
        'Tanzania': 'Pack neutral colored clothes for safari. Include comfortable walking shoes and camera with zoom lens. Carry cash for local purchases.',
        'Brazil': 'Pack beach gear for coastal visits. Include comfortable walking shoes for city exploration. Carry cash for local markets.',
        'UAE': 'Pack modest clothing for cultural respect. Include comfortable walking shoes for city exploration. Carry cash for local markets.',
        'Morocco': 'Pack modest clothing for cultural respect. Include comfortable walking shoes for medina exploration. Carry cash for local markets.',
        'Thailand': 'Pack beach gear for island visits. Include comfortable walking shoes for temple visits. Carry cash for local markets.'
    }
    
    return notes.get(country, 'Pack comfortable walking shoes and appropriate clothing for the season. Include essential travel documents and medications.')

# Enhanced review system with ratings and analytics
reviews_data = {}

@app.route('/api/reviews', methods=['POST'])
def create_review():
    try:
        data = request.get_json()
        destination_id = data.get('destination_id')
        rating = data.get('rating', 5)
        comment = data.get('comment', '')
        user_name = data.get('user_name', 'Anonymous')
        user_email = data.get('user_email', '')
        title = data.get('title')
        
        if not destination_id:
            return jsonify({'error': 'Destination ID required'}), 400
        
        # Try to persist to DB when ORM models available and user exists
        persisted = False
        if _DB_MODELS_AVAILABLE and DbReview is not None:
            try:
                db_user = None
                if user_email and DbUser is not None:
                    db_user = DbUser.query.filter_by(email=sanitize_input(user_email)).first()
                if db_user is None and user_email and DbUser is not None:
                    # Auto-create a minimal user to associate the review
                    uname = (user_name or (user_email.split('@')[0] if '@' in user_email else 'user')).strip() or 'user'
                    try:
                        new_user = DbUser(
                            username=uname,
                            email=sanitize_input(user_email),
                            password_hash='!',
                            first_name=None,
                            last_name=None,
                            created_at=datetime.now(),
                            is_active=True,
                        )
                        db.session.add(new_user)
                        db.session.commit()
                        db_user = new_user
                    except Exception as e:
                        db.session.rollback()
                        print(f"DB user create error: {e}")
                        db_user = None
                if db_user is not None:
                    db_review = DbReview(
                        user_id=db_user.id,
                        destination_id=int(destination_id),
                        rating=int(rating),
                        title=sanitize_input(title) if title else None,
                        content=sanitize_input(comment),
                        helpful_votes=0,
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    db.session.add(db_review)
                    db.session.commit()
                    persisted = True
            except Exception as e:
                db.session.rollback()
                print(f"DB review insert error: {e}")
                persisted = False
        
        # Raw-SQL fallback if ORM persist didn't happen
        if not persisted:
            try:
                from sqlalchemy import text
                # Ensure we have a user id: try by email, else create a minimal user row
                user_id_val = None
                if user_email:
                    user_email_s = sanitize_input(user_email)
                    row = db.session.execute(
                        text("SELECT id FROM users WHERE email=:email LIMIT 1"),
                        {"email": user_email_s}
                    ).first()
                    if row:
                        user_id_val = row[0]
                    else:
                        uname = (user_name or (user_email_s.split('@')[0] if '@' in user_email_s else 'user')).strip() or 'user'
                        db.session.execute(
                            text(
                                """
                                INSERT INTO users (username, email, password_hash, created_at, is_active)
                                VALUES (:uname, :email, '!', NOW(), 1)
                                """
                            ),
                            {"uname": uname, "email": user_email_s}
                        )
                        user_id_val = db.session.execute(
                            text("SELECT id FROM users WHERE email=:email ORDER BY id DESC LIMIT 1"),
                            {"email": user_email_s}
                        ).scalar()
                if user_id_val is None:
                    # Fallback to first existing user
                    user_id_val = db.session.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1")).scalar()
                    if user_id_val is None:
                        # As a last resort, create an anonymous user
                        db.session.execute(
                            text("INSERT INTO users (username, email, password_hash, created_at, is_active) VALUES ('anon','anon@example.com','!', NOW(), 1)")
                        )
                        user_id_val = db.session.execute(text("SELECT id FROM users WHERE email='anon@example.com' ORDER BY id DESC LIMIT 1")).scalar()
                # Now insert the review
                db.session.execute(
                    text(
                        """
                        INSERT INTO reviews (user_id, destination_id, rating, title, content, helpful_votes, created_at, updated_at)
                        VALUES (:user_id, :destination_id, :rating, :title, :content, 0, NOW(), NOW())
                        """
                    ),
                    {
                        'user_id': int(user_id_val),
                        'destination_id': int(destination_id),
                        'rating': int(rating),
                        'title': sanitize_input(title) if title else None,
                        'content': sanitize_input(comment),
                    }
                )
                db.session.commit()
                persisted = True
            except Exception as e:
                db.session.rollback()
                print(f"Raw SQL review insert error: {e}")
        
        # Initialize reviews for destination if not exists
        if destination_id not in reviews_data:
            reviews_data[destination_id] = []
        
        # Create new review
        review = {
            'id': len(reviews_data[destination_id]) + 1,
            'destination_id': destination_id,
            'rating': rating,
            'comment': comment,
            'user_name': user_name,
            'user_email': user_email,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'helpful_votes': 0,
            'verified_traveler': bool(user_email)
        }
        
        # Add review to destination
        reviews_data[destination_id].append(review)
        
        return jsonify({
            'message': 'Review created successfully' + (' (persisted)' if persisted else ''),
            'review': review
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reviews/<int:destination_id>', methods=['GET'])
def get_reviews(destination_id):
    try:
        # Prefer DB reviews when available, else fallback to in-memory
        db_reviews_list = []
        if _DB_MODELS_AVAILABLE and DbReview is not None:
            try:
                rows = DbReview.query.filter_by(destination_id=destination_id).order_by(DbReview.created_at.desc()).all()
                for r in rows:
                    db_reviews_list.append({
                        'id': r.id,
                        'destination_id': r.destination_id,
                        'rating': r.rating,
                        'title': r.title,
                        'comment': r.content,
                        'helpful_votes': r.helpful_votes or 0,
                        'created_at': r.created_at.isoformat() if r.created_at else None,
                        'user_id': r.user_id,
                    })
            except Exception:
                db_reviews_list = []
        # Merge with in-memory (DB first)
        mem_reviews = reviews_data.get(destination_id, [])
        reviews = db_reviews_list + mem_reviews
        
        # Calculate rating statistics
        rating_stats = calculate_rating_statistics(reviews)
        
        return jsonify({
            'reviews': reviews,
            'total': len(reviews),
            'rating_statistics': rating_stats,
            'average_rating': rating_stats['average_rating'] if reviews else 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reviews/analytics', methods=['GET'])
def reviews_analytics():
    """Return overall and per-destination review statistics for the Reviews page."""
    try:
        all_reviews: List[Dict[str, Any]] = []
        per_dest: Dict[int, List[Dict[str, Any]]] = {}
        # DB reviews first
        if _DB_MODELS_AVAILABLE and DbReview is not None:
            try:
                rows = DbReview.query.order_by(DbReview.created_at.desc()).all()
                for r in rows:
                    obj = {
                        'id': r.id,
                        'destination_id': int(r.destination_id),
                        'rating': int(r.rating or 0),
                        'comment': r.content or '',
                        'helpful_votes': int(r.helpful_votes or 0),
                        'created_at': r.created_at.isoformat() if r.created_at else None,
                        'user_id': r.user_id,
                    }
                    all_reviews.append(obj)
                    per_dest.setdefault(int(r.destination_id), []).append(obj)
            except Exception:
                pass
        # Merge in-memory reviews
        for dest_id, mem_list in reviews_data.items():
            for rev in mem_list:
                obj = {
                    'id': int(rev['id']),
                    'destination_id': int(rev['destination_id']),
                    'rating': int(rev['rating']),
                    'comment': rev.get('comment',''),
                    'helpful_votes': int(rev.get('helpful_votes', 0)),
                    'created_at': rev.get('created_at'),
                    'user_id': None,
                }
                all_reviews.append(obj)
                per_dest.setdefault(int(dest_id), []).append(obj)
        # Build stats
        overall_stats = calculate_overall_rating_statistics(all_reviews)
        destination_statistics: Dict[str, Any] = {}
        for d_id, lst in per_dest.items():
            stats = calculate_rating_statistics(lst)
            destination_statistics[str(d_id)] = {
                'destination_id': int(d_id),
                'count': stats['total_reviews'],
                'average_rating': stats['average_rating'],
                'rating_distribution': stats['rating_distribution'],
            }
        return jsonify({
            'overall_statistics': {
                'total_reviews': overall_stats['total_reviews'],
                'average_rating': overall_stats['average_rating'],
                'rating_distribution': overall_stats['rating_distribution'],
                'percentage_distribution': overall_stats['percentage_distribution'],
                'destination_statistics': destination_statistics
            },
            'destination_statistics': destination_statistics
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reviews/<int:destination_id>/vote', methods=['POST'])
def vote_review(destination_id):
    try:
        data = request.get_json()
        review_id = data.get('review_id')
        vote_type = data.get('vote_type', 'helpful')  # helpful, unhelpful
        
        # Try DB update first
        if _DB_MODELS_AVAILABLE and DbReview is not None and review_id:
            try:
                r = DbReview.query.filter_by(id=int(review_id), destination_id=destination_id).first()
                if r:
                    if vote_type == 'helpful':
                        r.helpful_votes = (r.helpful_votes or 0) + 1
                    r.updated_at = datetime.now()
                    db.session.commit()
                    return jsonify({'message': 'Vote recorded successfully', 'helpful_votes': r.helpful_votes or 0})
            except Exception:
                db.session.rollback()
                pass
        
        if destination_id not in reviews_data:
            return jsonify({'error': 'Destination not found'}), 404

        # Find and update review
        for review in reviews_data[destination_id]:
            if review['id'] == review_id:
                if vote_type == 'helpful':
                    review['helpful_votes'] += 1
                return jsonify({
                    'message': 'Vote recorded successfully',
                    'helpful_votes': review['helpful_votes']
                })
        
        return jsonify({'error': 'Review not found'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def calculate_rating_statistics(reviews):
    if not reviews:
        return {
            'average_rating': 0,
            'total_reviews': 0,
            'rating_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            'percentage_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        }
    
    total_reviews = len(reviews)
    total_rating = sum(review['rating'] for review in reviews)
    average_rating = total_rating / total_reviews
    
    # Calculate rating distribution
    rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for review in reviews:
        rating_distribution[review['rating']] += 1
    
    # Calculate percentage distribution
    percentage_distribution = {}
    for rating, count in rating_distribution.items():
        percentage_distribution[rating] = (count / total_reviews) * 100
    
    return {
        'average_rating': round(average_rating, 1),
        'total_reviews': total_reviews,
        'rating_distribution': rating_distribution,
        'percentage_distribution': percentage_distribution
    }

def calculate_overall_rating_statistics(all_reviews):
    if not all_reviews:
        return {
            'average_rating': 0,
            'total_reviews': 0,
            'rating_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            'percentage_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        }
    
    return calculate_rating_statistics(all_reviews)

# Enhanced API endpoints for comprehensive features



@app.route('/api/travel-time/<int:destination_id>', methods=['GET'])
def get_travel_time(destination_id):
    try:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Mock travel time data
        travel_info = {
            'destination': destination['name'],
            'from_major_cities': {
                'New York': {'flight': '6-8 hours', 'cost': '$800-1200'},
                'London': {'flight': '8-12 hours', 'cost': '$600-1000'},
                'Tokyo': {'flight': '12-16 hours', 'cost': '$1000-1500'},
                'Sydney': {'flight': '15-20 hours', 'cost': '$1200-1800'}
            },
            'transport_options': {
                'airplane': {'time': '6-20 hours', 'cost': '$600-1800'},
                'train': {'time': '24-48 hours', 'cost': '$200-500'},
                'bus': {'time': '48-72 hours', 'cost': '$100-300'}
            },
            'best_routes': [
                'Direct flights from major hubs',
                'Connecting flights via regional airports',
                'Train connections for nearby countries'
            ]
        }
        
        return jsonify(travel_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/hiking/<int:destination_id>', methods=['GET'])
def get_hiking_trails(destination_id):
    try:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Mock hiking trails data
        trails = [
            {
                'id': 1,
                'name': 'Mountain Peak Trail',
                'difficulty': 'Hard',
                'duration': '4-6 hours',
                'distance': '8 km',
                'elevation_gain': '800m',
                'description': 'Challenging hike with stunning panoramic views',
                'image': 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'coordinates': {'lat': destination['coordinates']['lat'] + 0.1, 'lng': destination['coordinates']['lng'] + 0.1},
                'best_time': 'Early morning',
                'safety_tips': ['Bring plenty of water', 'Check weather conditions', 'Wear proper hiking gear']
            },
            {
                'id': 2,
                'name': 'Forest Nature Walk',
                'difficulty': 'Easy',
                'duration': '2-3 hours',
                'distance': '5 km',
                'elevation_gain': '200m',
                'description': 'Easy scenic walk through beautiful forests',
                'image': 'https://images.unsplash.com/photo-1551524164-4876eb6e7aee?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'coordinates': {'lat': destination['coordinates']['lat'] - 0.1, 'lng': destination['coordinates']['lng'] - 0.1},
                'best_time': 'Afternoon',
                'safety_tips': ['Stay on marked trails', 'Bring insect repellent', 'Wear comfortable shoes']
            }
        ]
        
        return jsonify({
            'trails': trails,
            'total': len(trails)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/famous-food/<int:destination_id>', methods=['GET'])
def get_famous_food(destination_id):
    try:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Mock famous food data
        foods = [
            {
                'id': 1,
                'name': 'Local Specialty Dish',
                'description': 'Traditional local cuisine that represents the region',
                'price_range': '$15-25',
                'image': 'https://images.unsplash.com/photo-1565299624946-b28f40a0ca4b?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'rating': 4.5,
                'ingredients': ['Local spices', 'Fresh ingredients', 'Traditional methods'],
                'best_places': ['Local restaurants', 'Street food stalls', 'Traditional markets'],
                'dietary_info': {'vegetarian': True, 'vegan': False, 'gluten_free': False}
            },
            {
                'id': 2,
                'name': 'Street Food Delight',
                'description': 'Popular street food that locals love',
                'price_range': '$5-10',
                'image': 'https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'rating': 4.3,
                'ingredients': ['Street ingredients', 'Quick preparation', 'Local flavors'],
                'best_places': ['Street vendors', 'Night markets', 'Food courts'],
                'dietary_info': {'vegetarian': False, 'vegan': False, 'gluten_free': True}
            }
        ]
        
        return jsonify({
            'foods': foods,
            'total': len(foods)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/famous-items/<int:destination_id>', methods=['GET'])
def get_famous_items(destination_id):
    try:
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Mock famous items data
        items = [
            {
                'id': 1,
                'name': 'Local Handicrafts',
                'description': 'Beautiful handmade items by local artisans',
                'price_range': '$20-50',
                'image': 'https://images.unsplash.com/photo-1441986300917-64674bd600d8?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'category': 'Crafts',
                'best_places': ['Artisan markets', 'Local shops', 'Cultural centers'],
                'authenticity_tips': ['Look for handmade signs', 'Ask about the maker', 'Check for quality']
            },
            {
                'id': 2,
                'name': 'Traditional Souvenirs',
                'description': 'Authentic souvenirs that represent the culture',
                'price_range': '$10-30',
                'image': 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
                'category': 'Souvenirs',
                'best_places': ['Tourist shops', 'Airport stores', 'Local markets'],
                'authenticity_tips': ['Avoid mass-produced items', 'Support local businesses', 'Check origin labels']
            }
        ]
        
        return jsonify({
            'items': items,
            'total': len(items)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/detailed-budget/<int:destination_id>', methods=['POST'])
def get_detailed_budget(destination_id):
    try:
        data = request.get_json()
        duration = data.get('duration', 7)
        travelers = data.get('travelers', 2)
        style = data.get('style', 'mid')  # budget, mid, luxury
        
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Mock detailed budget breakdown
        budget_breakdown = {
            'destination': destination['name'],
            'duration': duration,
            'travelers': travelers,
            'style': style,
            'total_cost': 0,
            'breakdown': {
                'accommodation': {
                    'cost_per_night': {'budget': 50, 'mid': 150, 'luxury': 400}[style],
                    'total': 0,
                    'recommendations': ['Hotels', 'Hostels', 'Vacation rentals']
                },
                'food': {
                    'cost_per_day': {'budget': 30, 'mid': 70, 'luxury': 150}[style],
                    'total': 0,
                    'recommendations': ['Local restaurants', 'Street food', 'Fine dining']
                },
                'transportation': {
                    'cost_per_day': {'budget': 20, 'mid': 50, 'luxury': 100}[style],
                    'total': 0,
                    'recommendations': ['Public transport', 'Taxis', 'Private car']
                },
                'activities': {
                    'cost_per_day': {'budget': 40, 'mid': 100, 'luxury': 200}[style],
                    'total': 0,
                    'recommendations': ['Free attractions', 'Paid tours', 'Premium experiences']
                },
                'shopping': {
                    'cost_per_day': {'budget': 20, 'mid': 50, 'luxury': 100}[style],
                    'total': 0,
                    'recommendations': ['Local markets', 'Shopping districts', 'Luxury boutiques']
                }
            }
        }
        
        # Calculate totals
        for category in budget_breakdown['breakdown']:
            daily_cost = budget_breakdown['breakdown'][category]['cost_per_day']
            total_cost = daily_cost * duration * travelers
            budget_breakdown['breakdown'][category]['total'] = total_cost
            budget_breakdown['total_cost'] += total_cost
        
        return jsonify(budget_breakdown)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/comprehensive-packing/<int:destination_id>', methods=['POST'])
def get_comprehensive_packing_list(destination_id):
    try:
        data = request.get_json()
        duration = data.get('duration', 7)
        activities = data.get('activities', [])
        weather = data.get('weather', 'mild')
        
        destination = next((d for d in destinations if d['id'] == destination_id), None)
        
        if not destination:
            return jsonify({'error': 'Destination not found'}), 404
        
        # Comprehensive packing list
        packing_list = {
            'destination': destination['name'],
            'duration': duration,
            'essentials': [
                'Passport and travel documents',
                'Phone and charger',
                'Money and credit cards',
                'Travel insurance',
                'Emergency contacts',
                'Power adapter',
                'First aid kit'
            ],
            'clothing': {
                'casual': ['T-shirts', 'Jeans', 'Comfortable shoes', 'Underwear', 'Socks'],
                'formal': ['Dress shirts', 'Dress pants', 'Dress shoes'],
                'weather_specific': []
            },
            'toiletries': [
                'Toothbrush and toothpaste',
                'Shampoo and conditioner',
                'Deodorant',
                'Sunscreen',
                'Razor',
                'Hair brush',
                'Makeup (if needed)'
            ],
            'electronics': [
                'Camera',
                'Extra batteries',
                'Memory cards',
                'Laptop/tablet',
                'Headphones',
                'Portable charger'
            ],
            'activity_specific': [],
            'weather_specific': []
        }
        
        # Add weather-specific items
        if weather == 'cold':
            packing_list['weather_specific'].extend(['Warm jacket', 'Gloves', 'Scarf', 'Thermal underwear'])
        elif weather == 'hot':
            packing_list['weather_specific'].extend(['Light clothing', 'Hat', 'Sunglasses', 'Cooling towel'])
        elif weather == 'rainy':
            packing_list['weather_specific'].extend(['Rain jacket', 'Umbrella', 'Waterproof shoes'])
        
        # Add activity-specific items
        for activity in activities:
            if activity == 'hiking':
                packing_list['activity_specific'].extend(['Hiking boots', 'Backpack', 'Water bottle', 'Hiking poles'])
            elif activity == 'swimming':
                packing_list['activity_specific'].extend(['Swimsuit', 'Beach towel', 'Beach bag'])
            elif activity == 'photography':
                packing_list['activity_specific'].extend(['Camera equipment', 'Tripod', 'Lens cleaning kit'])
            elif activity == 'skiing':
                packing_list['activity_specific'].extend(['Ski equipment', 'Warm clothing', 'Goggles', 'Helmet'])
        
        return jsonify(packing_list)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Chatbot routes
@app.route('/chatbot')
def chatbot_page():
    """Render the chatbot UI page."""
    return render_template('chatbot.html')


def _chatbot_via_gemini(user_msg: str):
    """Call Gemini API to generate chatbot reply. Returns (reply, error)."""
    api_key = os.getenv('GEMINI_API_KEY') or app.config.get('GEMINI_API_KEY')
    if not api_key:
        return None, 'GEMINI_API_KEY not configured'
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': api_key,
        }
        prompt = (
            "You are a helpful travel assistant for the Mood Travel app. "
            "Answer concisely and helpfully. If the user mentions a destination, "
            "you may suggest checking weather, packing, attractions, or festivals pages.\n\n"
        ) + str(user_msg)
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if not resp.ok:
            return None, f"Gemini HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        # Handle safety blocks
        pf = data.get('promptFeedback') or {}
        if pf.get('blockReason'):
            return None, f"Gemini blocked: {pf.get('blockReason')}"
        candidates = data.get('candidates') or []
        if not candidates:
            return None, 'Gemini returned no candidates'
        content = candidates[0].get('content') or {}
        finish_reason = candidates[0].get('finishReason')
        if finish_reason and str(finish_reason).upper() in {"SAFETY", "BLOCKED"}:
            return None, f"Gemini finishReason: {finish_reason}"
        parts = content.get('parts') or []
        texts = [p.get('text') for p in parts if isinstance(p, dict) and p.get('text')]
        reply = "\n\n".join(texts).strip()
        if not reply:
            return None, 'Gemini produced empty reply'
        return reply, None
    except Exception as e:
        return None, str(e)


def _find_destination_by_text(text: str):
    """Try to map free-text to a destination using city, name, or country."""
    if not text:
        return None
    text_l = text.lower()
    # By city
    for d in destinations:
        city = d.get('city') or ''
        if city and city.lower() in text_l:
            return d
    # By destination name
    for d in destinations:
        name = d.get('name') or ''
        if name and name.lower() in text_l:
            return d
    # By country
    for d in destinations:
        country = d.get('country') or ''
        if country and country.lower() in text_l:
            return d
    return None


@app.route('/api/chatbot/message', methods=['POST'])
def chatbot_message():
    """Simple rule-based chatbot handler.
    Expects: {"message": "..."}
    Returns: {"reply": str, "links": []}
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        user_msg = (data.get('message') or '').strip()
        if not user_msg:
            return jsonify({'error': 'Empty message'}), 400

        # Prefer Gemini if configured
        reply, gemini_err = _chatbot_via_gemini(user_msg)
        if reply:
            # Derive quick-action links from user's message (booking intents)
            intent_links = []
            msg_l = user_msg.lower()
            if 'book' in msg_l and 'flight' in msg_l:
                intent_links.append({'title': 'Book a flight', 'url': '/flight_booking'})
            if 'book' in msg_l and ('bus' in msg_l or 'tour' in msg_l):
                intent_links.append({'title': 'Book a bus tour', 'url': '/bus_tours'})
            # Persist user and bot messages
            try:
                session_id = request.headers.get('X-Session-Id') or f"sess_{int(datetime.now().timestamp())}"
                user_msg_row = DbChatMessage(
                    user_id=None,
                    session_id=session_id,
                    role='user',
                    text=user_msg,
                    source='user'
                )
                bot_msg_row = DbChatMessage(
                    user_id=None,
                    session_id=session_id,
                    role='bot',
                    text=reply,
                    source='gemini'
                )
                db.session.add(user_msg_row)
                db.session.add(bot_msg_row)
                db.session.commit()
            except Exception:
                db.session.rollback()
            return jsonify({'reply': reply, 'links': intent_links, 'source': 'gemini'})

        # Rule-based fallback if Gemini unavailable
        msg_l = user_msg.lower()
        links = []
        reply_parts = []
        dest = _find_destination_by_text(user_msg)

        # Booking intents (flight / bus tour)
        if 'book' in msg_l and 'flight' in msg_l:
            links.append({'title': 'Book a flight', 'url': '/flight_booking'})
            reply_parts.append('You can book flights using the link below.')
        if 'book' in msg_l and ('bus' in msg_l or 'tour' in msg_l):
            links.append({'title': 'Book a bus tour', 'url': '/bus_tours'})
            reply_parts.append('You can book bus tours using the link below.')

        if 'weather' in msg_l:
            if dest:
                avg = dest.get('avg_temperature', {})
                reply_parts.append(
                    f"Weather for {dest['name']} (typical): min {avg.get('min','-')}°C, max {avg.get('max','-')}°C."
                )
                links.append({'title': f"Detailed weather for {dest['name']}", 'url': f"/weather/{dest['id']}"})
            else:
                reply_parts.append("Tell me the city or destination, e.g., 'Weather in Tokyo'.")

        if 'pack' in msg_l or 'packing' in msg_l:
            if dest:
                reply_parts.append(
                    f"For {dest['name']}: bring essentials (ID, charger, adapter), weather-appropriate clothing, and comfortable shoes."
                )
                links.append({'title': 'Generate detailed packing list', 'url': f"/packing"})
            else:
                reply_parts.append("I can generate a packing list if you mention a destination, e.g., 'What to pack for Greece?'")

        if 'attraction' in msg_l or 'must see' in msg_l or 'things to do' in msg_l:
            if dest:
                top = attractions.get(dest['id'], [])[:3]
                if top:
                    names = ', '.join(a['name'] for a in top)
                    reply_parts.append(f"Top attractions in {dest['name']}: {names}.")
                    links.append({'title': f"Explore attractions for {dest['name']}", 'url': f"/attractions/{dest['id']}"})
                else:
                    reply_parts.append(f"I couldn't find specific attractions for {dest['name']}.")
            else:
                reply_parts.append("Mention a place to see its top attractions, e.g., 'Attractions in Bali'.")

        if 'festival' in msg_l or 'events' in msg_l:
            if dest:
                fest = festivals.get(dest['id'], [])[:3]
                if fest:
                    names = ', '.join(f['name'] for f in fest)
                    reply_parts.append(f"Upcoming festivals near {dest['name']}: {names}.")
                    links.append({'title': f"View festivals for {dest['name']}", 'url': f"/festivals/{dest['id']}"})
                else:
                    reply_parts.append(f"No festivals data found for {dest['name']} right now.")
            else:
                reply_parts.append("Ask for festivals with a city, e.g., 'Festivals in Paris'.")

        if not reply_parts:
            reply_parts.append(
                "I can help with weather, packing, attractions, and festivals. Try: 'Weather in Tokyo', 'What should I pack for Greece?', or 'Attractions in Bali'."
            )

        reply = "\n".join(p for p in reply_parts if p)
        # Persist user and bot messages
        try:
            session_id = request.headers.get('X-Session-Id') or f"sess_{int(datetime.now().timestamp())}"
            user_msg_row = DbChatMessage(
                user_id=None,
                session_id=session_id,
                role='user',
                text=user_msg,
                source='user'
            )
            bot_msg_row = DbChatMessage(
                user_id=None,
                session_id=session_id,
                role='bot',
                text=reply,
                source='fallback'
            )
            db.session.add(user_msg_row)
            db.session.add(bot_msg_row)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'reply': reply, 'links': links, 'source': 'fallback', 'gemini_error': gemini_err})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Persistence endpoints to populate empty tables ---
@app.route('/api/visited/<int:destination_id>', methods=['POST'])
def mark_visited(destination_id):
    """Mark a destination as visited for a user (optional user_id)."""
    try:
        payload = request.get_json(silent=True) or {}
        user_id = payload.get('user_id')
        if 'DbVisitedPlace' in globals() and DbVisitedPlace is not None:
            row = DbVisitedPlace(user_id=user_id, destination_id=destination_id)
            db.session.add(row)
            db.session.commit()
            return jsonify({'status': 'ok', 'visited_place_id': row.id})
        else:
            from sqlalchemy import text
            res = db.session.execute(
                text("""
                    INSERT INTO visited_places (user_id, destination_id)
                    VALUES (:user_id, :destination_id)
                """),
                {"user_id": user_id, "destination_id": int(destination_id)}
            )
            db.session.commit()
            return jsonify({'status': 'ok'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/bookings', methods=['POST'])
def create_booking():
    """Create a generic booking record (hotel/tour/etc.)."""
    try:
        data = request.get_json() or {}
        # Coerce user_id to integer if possible; else create/lookup anonymous user
        uid = data.get('user_id')
        try:
            uid_int = int(uid) if uid is not None and str(uid).strip() != '' else None
        except Exception:
            uid_int = None
        if uid_int is None:
            try:
                from sqlalchemy import text
                # Try to find an existing anonymous user
                uid_int = db.session.execute(text("SELECT id FROM users WHERE email='anon@example.com' LIMIT 1")).scalar()
                if uid_int is None:
                    db.session.execute(text("INSERT INTO users (username, email, password_hash, created_at, is_active) VALUES ('anon','anon@example.com','!', NOW(), 1)"))
                    uid_int = db.session.execute(text("SELECT id FROM users WHERE email='anon@example.com' ORDER BY id DESC LIMIT 1")).scalar()
            except Exception:
                uid_int = None
        if 'DbBooking' in globals() and DbBooking is not None:
            row = DbBooking(
                user_id=uid_int,
                booking_type=data.get('booking_type'),
                booking_details=data.get('booking_details'),
                status=data.get('status', 'pending'),
                total_amount=float(data.get('total_amount', 0) or 0),
                currency=data.get('currency', 'USD'),
                booking_date=datetime.now(),
                travel_date=data.get('travel_date')
            )
            db.session.add(row)
            db.session.commit()
            return jsonify({'status': 'ok', 'booking_id': row.id})
        else:
            from sqlalchemy import text
            db.session.execute(
                text("""
                    INSERT INTO bookings (user_id, booking_type, booking_details, status, total_amount, currency, booking_date, travel_date)
                    VALUES (:user_id, :booking_type, :booking_details, :status, :total_amount, :currency, NOW(), :travel_date)
                """),
                {
                    'user_id': uid_int,
                    'booking_type': data.get('booking_type'),
                    'booking_details': json.dumps(data.get('booking_details') or {}),
                    'status': data.get('status', 'pending'),
                    'total_amount': float(data.get('total_amount', 0) or 0),
                    'currency': data.get('currency', 'USD'),
                    'travel_date': data.get('travel_date')
                }
            )
            db.session.commit()
            return jsonify({'status': 'ok'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/flight/book', methods=['POST'])
def create_flight_booking():
    """Create a flight booking entry."""
    try:
        data = request.get_json() or {}
        # Coerce user_id to integer if possible; else create/lookup anonymous user
        uid = data.get('user_id')
        try:
            uid_int = int(uid) if uid is not None and str(uid).strip() != '' else None
        except Exception:
            uid_int = None
        if uid_int is None:
            try:
                from sqlalchemy import text
                uid_int = db.session.execute(text("SELECT id FROM users WHERE email='anon@example.com' LIMIT 1")).scalar()
                if uid_int is None:
                    db.session.execute(text("INSERT INTO users (username, email, password_hash, created_at, is_active) VALUES ('anon','anon@example.com','!', NOW(), 1)"))
                    uid_int = db.session.execute(text("SELECT id FROM users WHERE email='anon@example.com' ORDER BY id DESC LIMIT 1")).scalar()
            except Exception:
                uid_int = None
        if 'FlightBooking' in globals() and FlightBooking is not None:
            row = FlightBooking(
                booking_id=data.get('booking_id') or f"FB{int(datetime.now().timestamp())}",
                flight_id=data.get('flight_id', 'N/A'),
                passenger_count=int(data.get('passenger_count') or 1),
                passenger_details=data.get('passenger_details'),
                contact_info=data.get('contact_info'),
                total_amount=float(data.get('total_amount') or 0),
                user_id=uid_int
            )
            db.session.add(row)
            db.session.commit()
            return jsonify({'status': 'ok', 'flight_booking_id': row.id, 'booking_id': row.booking_id})
        else:
            from sqlalchemy import text
            db.session.execute(
                text("""
                    INSERT INTO flight_bookings (booking_id, flight_id, passenger_count, passenger_details, contact_info, total_amount, user_id, created_at)
                    VALUES (:booking_id, :flight_id, :passenger_count, :passenger_details, :contact_info, :total_amount, :user_id, NOW())
                """),
                {
                    'booking_id': data.get('booking_id') or f"FB{int(datetime.now().timestamp())}",
                    'flight_id': data.get('flight_id', 'N/A'),
                    'passenger_count': int(data.get('passenger_count') or 1),
                    'passenger_details': json.dumps(data.get('passenger_details') or {}),
                    'contact_info': json.dumps(data.get('contact_info') or {}),
                    'total_amount': float(data.get('total_amount') or 0),
                    'user_id': uid_int
                }
            )
            db.session.commit()
            return jsonify({'status': 'ok'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Mood Travel Application...")
    print("🌍 Server starting on http://localhost:8000")
    print("📱 Open your browser and navigate to the URL above")
    print("🔗 All pages and API endpoints are now connected!")
    print("🗺️  Multi-page application with maps, attractions, festivals, and weather!")
    app.run(debug=True, host='0.0.0.0', port=8000)
