import os
import json
import requests
import openai
from flask import Flask, render_template, request, jsonify, session

# --- Configuration ---
app = Flask(__name__)
app.secret_key = os.urandom(24) 

# --- Reads secret keys from the server environment ---
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# --- Helper Functions ---

def moderate_query(user_input):
    """Uses an LLM to check if a query violates safety policies."""
    moderation_prompt = f"""You are a content moderator. Flag a query as "inappropriate" if it is sexually explicit, hateful, violent, promotes illegal acts or substances (drugs), or is malicious harassment. Respond with a single word: "safe" or "inappropriate". Query: "{user_input}" """
    try:
        response = openai.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": moderation_prompt}], temperature=0, max_tokens=5)
        decision = response.choices[0].message.content.strip().lower()
        return decision == "safe"
    except Exception as e:
        print(f"Moderation check failed: {e}"); return False

def refine_query_with_llm(conversation_history):
    """
    NEW INTELLIGENT PROMPT: This is the core fix for the refinement issue.
    """
    system_prompt = """
    You are an expert conversational query refiner for the Google Maps Places API. Your primary goal is to combine the user's entire conversation history into a single, optimized 5-6 word keyword phrase for the API.

    RULES:
    1.  **Always consider the full conversation history.** Do not treat new input in isolation.
    2.  When a user refines a search (e.g., adding "make it cheaper" or "with wheelchair access"), your job is to **merge their new input with the previous context** to create a new, more specific keyword.
    3.  You should **ONLY ask a clarifying question if the *entire conversation* is still impossibly vague** (e.g., the only input is "food"). If the user has provided enough detail for a search, do not ask for more.
    4.  Your output keyword must never contain comma-separated values.

    EXAMPLE 1: REFINEMENT
    - Conversation History: "User's initial request: spanish restaurants\nUser was not satisfied. New request: something romantic with outdoor seating"
    - Your Output: {"type": "keyword", "content": "romantic Spanish restaurant with outdoor seating"}

    EXAMPLE 2: VAGUE INITIAL QUERY
    - Conversation History: "User's initial request: I want lunch"
    - Your Output: {"type": "question", "content": "Sounds good! What type of food are you in the mood for?"}
    
    Your response format MUST be a JSON object with two keys: "type" (either "question" or "keyword") and "content".
    """
    try:
        response = openai.chat.completions.create(model="gpt-4o-mini", response_format={"type": "json_object"}, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": conversation_history}])
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error in refine_query_with_llm: {e}"); return {"type": "error", "content": "Sorry, I had trouble refining your query."}

def get_nearby_places(location, keyword, radius):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {'location': f"{location['lat']},{location['lng']}", 'radius': radius, 'keyword': keyword, 'key': GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(url, params=params); response.raise_for_status(); return response.json()
    except Exception as e:
        print(f"Error in get_nearby_places: {e}"); return None

def get_place_details_and_photos(place_id):
    details_url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {'place_id': place_id, 'fields': 'name,rating,reviews,photos,place_id,user_ratings_total', 'key': GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(details_url, params=params); response.raise_for_status()
        details = response.json().get('result', {})
        details['photo_urls'] = [f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={p.get('photo_reference')}&key={GOOGLE_MAPS_API_KEY}" for p in details.get('photos', [])[:3]]
        return details
    except Exception as e:
        print(f"Error in get_place_details_and_photos: {e}"); return None

def get_travel_times(origin, place_ids):
    if not place_ids: return {}
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {'origins': f"{origin['lat']},{origin['lng']}", 'destinations': '|'.join([f"place_id:{pid}" for pid in place_ids]), 'key': GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(url, params=params); response.raise_for_status()
        matrix = response.json()
        return {place_ids[i]: r.get('duration', {}).get('text', 'N/A') for i, r in enumerate(matrix.get('rows', [{}])[0].get('elements', [])) if r.get('status') == 'OK'}
    except Exception as e:
        print(f"Error getting travel times: {e}"); return {}

def get_final_recommendation(conversation_history, places_data, origin):
    lean_data_for_llm = [{'place_id': p.get('place_id'), 'name': p.get('name'), 'rating': p.get('rating'), 'reviews': [r.get('text', '') for r in p.get('reviews', [])[:3]]} for p in places_data]
    full_data_map = {p.get('place_id'): p for p in places_data}
    if not lean_data_for_llm: return None
    prompt = f"""From the list of places, analyze reviews to select the top two that best match: "{conversation_history}". Your response MUST be a JSON object with a key "recommended_ids" which is a list of the string place_ids for your two choices. Data: {json.dumps(lean_data_for_llm, indent=2)}"""
    try:
        response = openai.chat.completions.create(model="gpt-3.5-turbo", response_format={"type": "json_object"}, messages=[{"role": "system", "content": "You are a recommender. Always respond in the requested JSON format."}, {"role": "user", "content": prompt}])
        llm_output = json.loads(response.choices[0].message.content)
        recommended_ids = llm_output.get("recommended_ids", [])
        travel_times = get_travel_times(origin, recommended_ids)
        final_recs = []
        for pid in recommended_ids:
            if pid in full_data_map:
                place_data = full_data_map[pid]
                place_data['link'] = f"https://www.google.com/maps/place/?q=place_id:{pid}"
                place_data['travel_time'] = travel_times.get(pid, 'N/A')
                final_recs.append(place_data)
        return {"recommendations": final_recs}
    except Exception as e:
        print(f"Error in get_final_recommendation: {e}"); return None

# --- Flask Routes ---
@app.route("/")
def home():
    session.clear(); return render_template("index.html")

@app.route("/app", methods=["POST"])
def app_page():
    session.clear(); session['initial_query'] = request.form.get("query"); return render_template("app.html")

@app.route("/get_recommendation", methods=["POST"])
def get_recommendation_route():
    data = request.json; location = data.get("location"); user_input = data.get("query"); is_feedback = data.get("is_feedback", False)
    
    if 'conversation' not in session:
        if not moderate_query(user_input): return jsonify({"type": "error", "content": "This search is not permitted."})
        session['conversation'] = f"User's initial request: {user_input}"
        session['excluded_ids'], session['retries'] = [], 0
    else:
        if is_feedback:
            if not moderate_query(user_input): return jsonify({"type": "error", "content": "This search is not permitted."})
            if session.get('retries', 0) >= 2: return jsonify({"type": "final_message", "content": "I've tried my best. Let's start a new search!"})
            session['retries'] += 1
            session['conversation'] += f"\nUser was not satisfied. New request: {user_input}"
        else:
             session['conversation'] += f"\nMy Answer: {user_input}"

    if data.get("distance"): session['travel_distance'] = int(data.get("distance"))
    if data.get('expand_search'): session['travel_distance'] = 20000

    llm_response = refine_query_with_llm(session['conversation'])
    if llm_response.get("type") != "keyword": return jsonify(llm_response)

    final_keyword = llm_response.get("content")
    session['last_keyword'] = final_keyword
    
    current_distance = session.get('travel_distance', 3000)
    nearby_places = get_nearby_places(location, final_keyword, current_distance)

    if not nearby_places or not nearby_places.get('results'):
        if current_distance < 20000:
            return jsonify({"type": "expand_search", "message": "I couldn't find anything in that range. Would you like to expand the search area?"})
        else:
            return jsonify({"type": "error", "content": "I couldn't find any places, even in a wider area."})

    unseen_places = [p for p in nearby_places['results'] if p.get('place_id') not in session.get('excluded_ids', [])]
    
    # MODIFIED SECTION: This part is now simpler and safer.
    if not unseen_places:
        return jsonify({"type": "error", "content": "I couldn't find any new places matching your refined search. Try broadening your criteria or starting a new search."})
    
    detailed_places = [get_place_details_and_photos(p.get('place_id')) for p in unseen_places[:7] if p.get('place_id')]
    final_recs_data = get_final_recommendation(session['conversation'], [d for d in detailed_places if d], location)

    if not final_recs_data or not final_recs_data.get("recommendations"):
        return jsonify({"type": "error", "content": "The AI had trouble picking final recommendations. Please try again."})

    session['excluded_ids'].extend([p.get('place_id') for p in final_recs_data["recommendations"]])
    final_recs_data['last_keyword'] = final_keyword
    
    # REMOVED the line that caused the error. The session will no longer store the large results data.
    
    session.modified = True
    return jsonify({"type": "recommendation", "data": final_recs_data})

@app.route("/history")
def history_page():
    return render_template("history.html")

if __name__ == "__main__":
    app.run(debug=True)
