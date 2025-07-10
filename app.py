import os
import json
import requests
import openai
import urllib.parse
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
    # --- REPLACED WITH THE NEW, MORE PRECISE PROMPT ---
    moderation_prompt = f"""
    You are a content safety moderator for a local business search app. Your goal is to flag ONLY a very narrow set of harmful queries. You must allow searches for all legal businesses, including those for adults.

    ALLOWED (mark as "safe"): Any queries for legal businesses, including bars, wineries, breweries, strip clubs, adult stores, and cannabis dispensaries. Use of slang like "killer view" or "food to die for" is also safe.

    INAPPROPRIATE (mark as "inappropriate"): ONLY flag queries that are:
    1. Seeking illegal hard drugs (e.g., cocaine, heroin).
    2. Requesting pornography or illegal sexual content.
    3. Genuinely hateful, harassing, or promoting self-harm.

    Respond with a single word: "safe" or "inappropriate".

    Query: "{user_input}"
    """
    try:
        response = openai.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": "You are a content safety moderator."}, {"role": "user", "content": moderation_prompt}], temperature=0, max_tokens=5)
        decision = response.choices[0].message.content.strip().lower().replace('"', '').replace('.', '')
        return decision == "safe"
    except Exception as e:
        print(f"Moderation check failed: {e}"); return False

def refine_query_with_llm(conversation_history):
    """
    Takes the entire conversation history with the user and uses a powerful AI
    model (GPT-4o mini) to create a single, perfect search keyword for Google Maps.
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
    """
    Searches the Google Maps API for places matching a keyword near a specific location.
    """
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {'location': f"{location['lat']},{location['lng']}", 'radius': radius, 'keyword': keyword, 'key': GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(url, params=params); response.raise_for_status(); return response.json()
    except Exception as e:
        print(f"Error in get_nearby_places: {e}"); return None

def get_place_details_and_photos(place_id):
    """
    Gets detailed information for a single place, including rating, reviews, photos,
    and other critical metadata for AI ranking.
    """
    details_url = "https://maps.googleapis.com/maps/api/place/details/json"
    # --- UPDATED FIELDS ---
    fields_to_request = 'name,place_id,rating,reviews,photos,user_ratings_total,price_level,types,editorial_summary,wheelchair_accessible_entrance'
    params = {'place_id': place_id, 'fields': fields_to_request, 'key': GOOGLE_MAPS_API_KEY}
    
    try:
        response = requests.get(details_url, params=params); response.raise_for_status()
        details = response.json().get('result', {})
        details['photo_urls'] = [f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={p.get('photo_reference')}&key={GOOGLE_MAPS_API_KEY}" for p in details.get('photos', [])[:3]]
        return details
    except Exception as e:
        print(f"Error in get_place_details_and_photos: {e}"); return None

def get_travel_times(origin, place_ids):
    """
    Uses the Google Maps Distance Matrix API to calculate the travel time from
    the user's location to a list of recommended places.
    """
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
    """
    Uses a powerful AI to analyze, score, and rank a list of places based on
    user's conversation, place details, and travel time.
    """
    if not places_data: return None

    # Get all the place IDs from the detailed data we've fetched.
    place_ids_to_rank = [p['place_id'] for p in places_data if 'place_id' in p]
    if not place_ids_to_rank: return None
    
    # Call the Distance Matrix API for all candidates *before* calling the LLM.
    travel_times_map = get_travel_times(origin, place_ids_to_rank)

    # Include all rich data in the payload for the LLM
    lean_data_for_llm = []
    for p in places_data:
        place_id = p.get('place_id')
        if place_id:
            lean_data_for_llm.append({
                'place_id': place_id,
                'name': p.get('name'),
                'types': p.get('types', []),
                'rating': p.get('rating'),
                'review_count': p.get('user_ratings_total'),
                'price_level': p.get('price_level'),
                'travel_time': travel_times_map.get(place_id, 'N/A'),
                'wheelchair_accessible': p.get('wheelchair_accessible_entrance'),
                'summary': p.get('editorial_summary', {}).get('overview', 'No summary available.'),
                'reviews': [r.get('text', '') for r in p.get('reviews', [])[:5]] # Increased to 5 reviews
            })

    # --- NEW, ADVANCED SYSTEM PROMPT ---
    system_prompt = """
    You are an expert local guide and recommendation concierge. Your goal is to analyze a list of potential places and rank them according to a user's specific request. You must provide a structured, reasoned analysis for your rankings.

    **TASK:**
    1.  Analyze the user's conversation history to deeply understand their needs (e.g., ambiance, price, occasion, specific features).
    2.  For each place in the provided JSON data, evaluate it based on the user's request.
    3.  You will score each place on FOUR criteria, from 1 (poor match) to 10 (perfect match):
        - **Relevance Score**: How well do the place's `types`, `summary`, and `reviews` match the user's explicit request (e.g., "cozy cafe", "romantic italian restaurant")?
        - **Quality Score**: A combination of the `rating` and `review_count`. A high rating with many reviews is a 10. A low rating or very few reviews is a 1.
        - **Vibe Score**: Based on the language in the `reviews`, does the atmosphere (e.g., "lively", "quiet", "trendy", "family-friendly") match the implicit mood of the user's request?
        - **Convenience Score**: Based on the `travel_time`. A shorter travel time gets a higher score (e.g., <10 mins is a 10, >45 mins is a 1).
    4.  Provide a `final_score` which is a weighted average of the four scores.
    5.  Write a concise `justification` (20-30 words) for your ranking, explaining why this place is a good match, considering all factors including travel time.
    6.  Return a single JSON object containing a key "ranked_recommendations". The value should be a list of all analyzed places, sorted from highest `final_score` to lowest.

    **OUTPUT FORMAT (Strict):**
    {
      "ranked_recommendations": [
        {
          "place_id": "string",
          "name": "string",
          "relevance_score": integer,
          "quality_score": integer,
          "vibe_score": integer,
          "convenience_score": integer,
          "final_score": float,
          "justification": "string"
        },
        ...
      ]
    }
    """
    
    user_prompt = f"""
    User's conversation history:
    ---
    {conversation_history}
    ---
    
    Data for the places to rank:
    ---
    {json.dumps(lean_data_for_llm, indent=2)}
    ---
    
    Please provide your ranked analysis in the specified JSON format.
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        llm_output = json.loads(response.choices[0].message.content)
        
        ranked_recs_from_llm = llm_output.get("ranked_recommendations", [])
        if not ranked_recs_from_llm: return None

        full_data_map = {p.get('place_id'): p for p in places_data}
        
        final_recs = []
        for llm_item in ranked_recs_from_llm:
            pid = llm_item.get('place_id')
            if pid and pid in full_data_map:
                place_data = full_data_map[pid]
                place_name = urllib.parse.quote_plus(place_data.get('name', ''))
                place_data['link'] = f"https://www.google.com/maps/search/?api=1&query={place_name}&query_place_id={pid}"
                place_data['travel_time'] = travel_times_map.get(pid, 'N/A')
                # We DO NOT add the justification or scores to the final output.
                # The final object remains clean for the user.
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
    
    if not unseen_places:
        return jsonify({"type": "error", "content": "I couldn't find any new places matching your refined search. Try broadening your criteria or starting a new search."})
    
    # Increase the number of places we analyze from 7 to 15
    detailed_places = [get_place_details_and_photos(p.get('place_id')) for p in unseen_places[:15] if p.get('place_id')]
    final_recs_data = get_final_recommendation(session['conversation'], [d for d in detailed_places if d], location)

    if not final_recs_data or not final_recs_data.get("recommendations"):
        return jsonify({"type": "error", "content": "The AI had trouble picking final recommendations. Please try again."})

    # Exclude all places that were considered in this round from future rounds
    session['excluded_ids'].extend([p.get('place_id') for p in detailed_places])
    final_recs_data['last_keyword'] = final_keyword
    
    session.modified = True
    return jsonify({"type": "recommendation", "data": final_recs_data})

@app.route("/history")
def history_page():
    return render_template("history.html")

if __name__ == "__main__":
    app.run(debug=True)
