from textblob import TextBlob
import re
from datetime import datetime

class AIService:
    def __init__(self):
        # Mood keywords for classification
        self.mood_keywords = {
            'happy': ['happy', 'joyful', 'excited', 'thrilled', 'delighted'],
            'relaxed': ['relaxed', 'calm', 'peaceful', 'tranquil', 'serene'],
            'stressed': ['stressed', 'anxious', 'worried', 'overwhelmed', 'tense'],
            'adventurous': ['adventurous', 'excited', 'thrilled', 'energetic', 'pumped'],
            'romantic': ['romantic', 'loving', 'passionate', 'intimate', 'sweet']
        }
        # Initialize ML service for improved mood prediction (optional)
        self.ml = None
        try:
            from services.ml_service import MLService  # lazy import to avoid heavy deps at startup
            self.ml = MLService()
        except Exception:
            self.ml = None
    
    def analyze_mood(self, text):
        """Analyze mood from text input"""
        if not text or not text.strip():
            return {
                'mood': 'neutral',
                'intensity': 5,
                'confidence': 0.5,
                'sentiment': {'polarity': 0, 'subjectivity': 0},
                'text_input': text
            }
        
        # Clean text
        text = text.lower().strip()
        
        # Try ML-based mood prediction first (if available)
        ml_result = {"status": "no_model"}
        ml_available = False
        if self.ml is not None:
            try:
                ml_result = self.ml.predict(text)
                ml_available = ml_result.get('status') == 'ok'
            except Exception:
                ml_available = False
        
        # Sentiment analysis using TextBlob (used for fallback and extra context)
        blob = TextBlob(text)
        sentiment = {
            'polarity': blob.sentiment.polarity,
            'subjectivity': blob.sentiment.subjectivity
        }
        
        # Keyword-based mood detection
        mood_scores = {}
        for mood, keywords in self.mood_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            mood_scores[mood] = score
        
        # Determine primary mood
        if ml_available:
            mood = ml_result.get('mood', 'neutral')
            ml_conf = float(ml_result.get('confidence', 0.5))
        else:
            if mood_scores:
                primary_mood = max(mood_scores, key=mood_scores.get)
                if mood_scores[primary_mood] > 0:
                    mood = primary_mood
                else:
                    # Fall back to sentiment-based mood
                    if sentiment['polarity'] > 0.3:
                        mood = 'happy'
                    elif sentiment['polarity'] < -0.3:
                        mood = 'stressed'
                    else:
                        mood = 'neutral'
            else:
                # Sentiment-based mood
                if sentiment['polarity'] > 0.3:
                    mood = 'happy'
                elif sentiment['polarity'] < -0.3:
                    mood = 'stressed'
                else:
                    mood = 'neutral'
        
        # Calculate intensity (1-10)
        intensity = min(10, max(1, int(abs(sentiment['polarity']) * 10 + 5)))
        
        # Calculate confidence
        if ml_available:
            confidence = ml_conf
        else:
            confidence = min(1.0, max(0.3, abs(sentiment['polarity']) + 0.5))
        
        return {
            'mood': mood,
            'intensity': intensity,
            'confidence': round(confidence, 2),
            'sentiment': sentiment,
            'text_input': text
        }
    
    def get_recommendations(self, user, filters=None):
        """Generate personalized recommendations"""
        if filters is None:
            filters = {}
        
        current_mood = user.get_current_mood()
        user_preferences = user.preferences or {}
        
        # Get all active destinations
        from models.destination import Destination
        destinations = Destination.query.filter_by(is_active=True).all()
        
        recommendations = []
        
        for destination in destinations:
            score = self.calculate_recommendation_score(
                destination, user, current_mood, user_preferences, filters
            )
            
            if score > 0.3:
                recommendations.append({
                    'destination': destination.to_dict(),
                    'score': round(score, 3),
                    'reasons': self.get_recommendation_reasons(destination, user, current_mood)
                })
        
        # Sort by score (highest first)
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations[:10]
    
    def calculate_recommendation_score(self, destination, user, current_mood, preferences, filters):
        """Calculate recommendation score for a destination"""
        score = 0.0
        
        # Mood compatibility (30% weight)
        if current_mood:
            mood_compatibility = destination.get_mood_compatibility(current_mood.get('mood', 'neutral'))
            score += mood_compatibility * 0.3
        
        # Travel style match (25% weight)
        user_styles = preferences.get('travel_style', [])
        destination_styles = destination.travel_styles or []
        
        if user_styles and destination_styles:
            style_match = len(set(user_styles) & set(destination_styles)) / len(user_styles)
            score += style_match * 0.25
        
        # Overall rating (20% weight)
        overall_rating = destination.ratings.get('overall', 0) if destination.ratings else 0
        score += (overall_rating / 5) * 0.2
        
        # Budget compatibility (15% weight)
        user_budget = preferences.get('budget', {})
        if user_budget and destination.cost:
            avg_cost = destination.get_average_cost()
            min_budget = user_budget.get('min', 0)
            max_budget = user_budget.get('max', float('inf'))
            
            if min_budget <= avg_cost <= max_budget:
                score += 0.15
        
        # Interest match (10% weight)
        user_interests = preferences.get('interests', [])
        destination_activities = destination.activities or []
        
        if user_interests and destination_activities:
            activity_types = [act.get('type') for act in destination_activities]
            interest_match = len(set(user_interests) & set(activity_types)) / len(user_interests)
            score += interest_match * 0.1
        
        return min(1.0, max(0.0, score))
    
    def get_recommendation_reasons(self, destination, user, current_mood):
        """Get reasons why a destination is recommended"""
        reasons = []
        
        # Mood-based reason
        if current_mood:
            mood = current_mood.get('mood', 'neutral')
            compatibility = destination.get_mood_compatibility(mood)
            if compatibility > 0.7:
                reasons.append(f"Perfect for your {mood} mood")
        
        # Rating reason
        overall_rating = destination.ratings.get('overall', 0) if destination.ratings else 0
        if overall_rating >= 4.0:
            reasons.append(f"Highly rated by travelers ({overall_rating:.1f}/5)")
        
        return reasons
    
    def generate_packing_list(self, destination, activities, duration):
        """Generate packing list"""
        packing_list = {
            'essentials': ['Passport', 'Phone charger', 'Money/cards'],
            'clothing': ['Comfortable clothes'],
            'activities': []
        }
        
        # Activity-based items
        for activity in activities:
            activity_type = activity.get('type', '')
            
            if activity_type == 'hiking':
                packing_list['activities'].extend(['Hiking boots', 'Backpack', 'Water bottle'])
            elif activity_type == 'swimming':
                packing_list['activities'].extend(['Swimsuit', 'Beach towel'])
            elif activity_type == 'photography':
                packing_list['activities'].extend(['Camera', 'Extra batteries'])
        
        return packing_list
    
    def estimate_trip_cost(self, destination, duration, group_size, accommodation_type='mid'):
        """Estimate trip cost"""
        cost_data = destination.cost or {}
        
        # Simplified cost calculation
        accommodation_cost = 100 * duration * group_size
        food_cost = 50 * duration * group_size * 3
        transport_cost = 30 * duration * group_size
        activities_cost = 40 * duration * group_size
        
        total_cost = accommodation_cost + food_cost + transport_cost + activities_cost
        
        return {
            'accommodation': accommodation_cost,
            'food': food_cost,
            'transport': transport_cost,
            'activities': activities_cost,
            'total': total_cost,
            'per_person': total_cost / group_size if group_size > 0 else 0
        } 
 