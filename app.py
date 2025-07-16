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

# --- The Plan Book ---
plan_book = {
    "date_night": {
        "display_title": "for a Casual Date Night",
        "base_prompt": "A spot for a date that is relaxed, cozy, and intimate, suitable for conversation. It shouldn't be too loud or overly expensive. Atmosphere is more important than a specific food type.",
        "questions": [
            {"id": "vibe", "text": "What's the vibe?", "type": "multiple_choice", "options": [
                {"value": "cozy_romantic", "display_text": "Cozy & Romantic"},
                {"value": "lively_fun", "display_text": "Lively & Fun"},
                {"value": "trendy_modern", "display_text": "Trendy & Modern"}
            ]},
            {"id": "budget", "text": "What's the budget?", "type": "multiple_choice", "options": [
                {"value": "budget_friendly", "display_text": "💰"},
                {"value": "nice_treat", "display_text": "💰💰"},
                {"value": "splurge", "display_text": "💰💰💰"}
            ]},
            {"id": "cuisine", "text": "Any specific cuisine in mind? (Optional)", "type": "text_input", "options": [{"display_text": "e.g., Italian, Sushi, Tacos..."}]}
        ]
    },
    "client_dinner": {
        "display_title": "to Impress a Client",
        "base_prompt": "A professional, impressive restaurant with high-quality service and excellent food. It should be relatively quiet and suitable for a business meeting. Price is a secondary concern to quality and atmosphere.",
        "questions": [
             {"id": "formality", "text": "How formal should it be?", "type": "multiple_choice", "options": [
                {"value": "business_casual", "display_text": "Business Casual"},
                {"value": "formal_dining", "display_text": "Formal Dining"},
                {"value": "modern_upscale", "display_text": "Modern & Upscale"}
            ]},
            {"id": "cuisine", "text": "Preferred cuisine? (e.g., Steakhouse, Japanese)", "type": "text_input", "options": [{"display_text": "Leave blank for best overall"}]}
        ]
    },
    "birthday_celebration": {
        "display_title": "for a Birthday Celebration",
        "base_prompt": "A fun, celebratory, and lively place suitable for a group. It should feel special but not necessarily formal. Good for photos and a festive atmosphere.",
        "questions": [
            {"id": "group_size", "text": "How large is the group?", "type": "multiple_choice", "options": [
                {"value": "small_group", "display_text": "Small (2-4)"},
                {"value": "medium_group", "display_text": "Medium (5-8)"},
                {"value": "large_group", "display_text": "Large (8+)"}
            ]},
            {"id": "vibe", "text": "What's the vibe?", "type": "multiple_choice", "options": [
                {"value": "party_atmosphere", "display_text": "Party Atmosphere"},
                {"value": "family_friendly", "display_text": "Family Friendly"},
                {"value": "upscale_celebration", "display_text": "Upscale & Classy"}
            ]},
            {"id": "budget", "text": "What's the budget per person?", "type": "multiple_choice", "options": [
                {"value": "budget_friendly", "display_text": "Under $30"},
                {"value": "nice_treat", "display_text": "$30 - $60"},
                {"value": "splurge", "display_text": "$60+"}
            ]}
        ]
    },
    "coffee_focus": {
        "display_title": "for Coffee & Focus",
        "base_prompt": "A coffee shop with a good atmosphere for focusing or having a quiet conversation.",
        "questions": [
             {"id": "primary_goal", "text": "What's the main goal?", "type": "multiple_choice", "options": [
                {"value": "get_work_done", "display_text": "💻 Get Work Done"},
                {"value": "catch_up", "display_text": "🗣️ Catch Up with a Friend"},
                {"value": "read_a_book", "display_text": "📖 Read a Book"}
            ]},
            {"id": "noise_level", "text": "Preferred noise level?", "type": "multiple_choice", "options": [
                {"value": "quiet", "display_text": "🤫 Pin-drop Quiet"},
                {"value": "background_buzz", "display_text": "🎶 Background Buzz"},
                {"value": "doesnt_matter", "display_text": "Any"}
            ]}
        ]
    },
    "family_dinner": {
        "display_title": "for a Family Dinner",
        "base_prompt": "A comfortable, family-friendly restaurant. It should be welcoming to all ages, not too loud, and have a broad menu that can satisfy different tastes.",
        "questions": [
            {"id": "ages", "text": "Are there young children?", "type": "multiple_choice", "options": [
                {"value": "with_kids", "display_text": "Yes, with kids"},
                {"value": "all_adults", "display_text": "No, all adults/teens"}
            ]},
            {"id": "price", "text": "What's the price point?", "type": "multiple_choice", "options": [
                {"value": "casual_cheap", "display_text": "Casual & Cheap"},
                {"value": "mid_range", "display_text": "Mid-Range"},
                {"value": "special_occasion", "display_text": "A Special Occasion"}
            ]},
            {"id": "cuisine", "text": "Any food preferences?", "type": "text_input", "options": [{"display_text": "e.g., Pizza, American, Chinese"}]}
        ]
    },
    "hidden_gem": {
        "display_title": "to Find a Hidden Gem",
        "base_prompt": "A unique, non-touristy, and highly-rated spot that feels like a local secret. It could be any type of place - a cafe, a bar, a small restaurant, or a unique shop. The key is authenticity and a sense of discovery.",
        "questions": [
             {"id": "type_of_gem", "text": "What kind of gem are you seeking?", "type": "multiple_choice", "options": [
                {"value": "food_drink", "display_text": "Food & Drink"},
                {"value": "experience_shop", "display_text": "Experience / Shop"},
                {"value": "any_gem", "display_text": "Surprise Me"}
            ]}
        ]
    }
}


# --- Helper Functions ---

def moderate_query(user_input):
    if not user_input or not isinstance(user_input, str) or not user_input.strip():
        return False
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
    system_prompt = """
    You are an expert conversational query refiner for the Google Maps Places API. Your primary goal is to combine the user's entire conversation history into a single, optimized keyword phrase for the API. This phrase should be a maximum of 9 words.

    RULES:
    1.  **Always consider the full conversation history.** Do not treat new input in isolation.
    2.  When a user refines a search (e.g., adding "make it cheaper" or "with wheelchair access"), your job is to **merge their new input with the previous context** to create a new, more specific keyword.
    3.  You should **ONLY ask a clarifying question if the *entire conversation* is still impossibly vague** (e.g., the only input is "food"). If the user has provided enough detail for a search, do not ask for more.
    4.  Your output keyword must never contain comma-separated values.
    5.  **Crucially, ensure the final keyword phrase is no more than 9 words long.** If necessary, prioritize the most important keywords or use more concise phrasing.

    EXAMPLE 1: REFINEMENT
    - Conversation History: "User's initial request: A spot for a date that is relaxed, cozy, and intimate, suitable for conversation. For 'What's the vibe?', the user specified 'cozy_romantic'."
    - Your Output: {"type": "keyword", "content": "cozy romantic intimate relaxed restaurant"}

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
    if not places_data: return None
    place_ids_to_rank = [p['place_id'] for p in places_data if 'place_id' in p]
    if not place_ids_to_rank: return None
    travel_times_map = get_travel_times(origin, place_ids_to_rank)
    lean_data_for_llm = []
    total_reviews = 0
    for p in places_data:
        place_id = p.get('place_id')
        if place_id:
            # Truncate each review to 200 characters
            reviews = [r.get('text', '')[:200] for r in p.get('reviews', [])[:5]]
            total_reviews += len(reviews)
            lean_data_for_llm.append({
                'place_id': place_id, 'name': p.get('name'), 'types': p.get('types', []),
                'rating': p.get('rating'), 'review_count': p.get('user_ratings_total'),
                'price_level': p.get('price_level'), 'travel_time': travel_times_map.get(place_id, 'N/A'),
                'wheelchair_accessible': p.get('wheelchair_accessible_entrance'),
                'summary': p.get('editorial_summary', {}).get('overview', 'No summary available.'),
                'reviews': reviews
            })
    import sys
    import json as _json
    print(f"[DEBUG] Number of places sent to LLM: {len(lean_data_for_llm)}")
    print(f"[DEBUG] Total reviews sent to LLM: {total_reviews}")
    print(f"[DEBUG] Estimated JSON size sent to LLM: {len(_json.dumps(lean_data_for_llm))} bytes")

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
    { "ranked_recommendations": [ { "place_id": "string", "name": "string", "relevance_score": integer, "quality_score": integer, "vibe_score": integer, "convenience_score": integer, "final_score": float, "justification": "string" }, ... ] }
    """
    user_prompt = f"User's conversation history:\n---\n{conversation_history}\n---\n\nData for the places to rank:\n---\n{json.dumps(lean_data_for_llm, indent=2)}\n---\n\nPlease provide your ranked analysis in the specified JSON format."

    try:
        response = openai.chat.completions.create(model="gpt-4o-mini", response_format={"type": "json_object"}, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
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
                final_recs.append(place_data)
        return {"recommendations": final_recs}
    except Exception as e:
        print(f"Error in get_final_recommendation: {e}"); return None

# --- Flask Routes ---
@app.route("/")
def home():
    session.clear()
    return render_template("index.html")

@app.route("/refine", methods=["POST"])
def refine_page():
    session.clear()
    plan_id = request.form.get("plan_id")
    if plan_id and plan_id in plan_book:
        return render_template("refine.html", plan_id=plan_id, plan=plan_book[plan_id])
    return redirect(url_for('home'))

@app.route("/app", methods=["POST"])
def app_page():
    session.clear()
    form_data = request.form

    if 'query' in form_data and form_data.get('query'):
        session['initial_query'] = form_data.get('query')
        session['display_title'] = "for your search"
        return render_template("app.html")

    elif 'plan_id' in form_data:
        plan_id = form_data.get('plan_id')
        plan = plan_book.get(plan_id)
        if not plan:
            return redirect(url_for('home'))

        initial_prompt = [plan['base_prompt']]
        session['display_title'] = plan['display_title']
        
        if form_data.get('action') == 'get_recommendations':
            for question in plan['questions']:
                q_id = question['id']
                if q_id in form_data and form_data[q_id]:
                    initial_prompt.append(f"For '{question['text']}', the user specified '{form_data[q_id]}'.")
        
        session['initial_query'] = " ".join(initial_prompt)
        return render_template("app.html")
    
    return redirect(url_for('home'))


@app.route("/get_recommendation", methods=["POST"])
def get_recommendation_route():
    try:
        print("[DEBUG] Incoming /get_recommendation request")
        data = request.json
        print(f"[DEBUG] Request data: {data}")
        print(f"[DEBUG] Session before processing: {dict(session)}")
        location = data.get("location")
        user_input = data.get("query")
        is_feedback = data.get("is_feedback", False)
        
        # Defensive check for user_input
        if not user_input or not isinstance(user_input, str) or not user_input.strip():
            print("[DEBUG] user_input is missing or empty.")
            return jsonify({"type": "error", "content": "No user input provided."})

        if 'conversation' not in session:
            if not moderate_query(user_input): 
                print("[DEBUG] Query flagged as inappropriate by moderation.")
                return jsonify({"type": "error", "content": "This search is not permitted."})
            session['conversation'] = f"User's initial request: {user_input}"
            session['excluded_ids'] = []
            session['retries'] = 0
        else:
            if is_feedback:
                if not moderate_query(user_input): 
                    print("[DEBUG] Feedback query flagged as inappropriate by moderation.")
                    return jsonify({"type": "error", "content": "This search is not permitted."})
                if session.get('retries', 0) >= 2: 
                    print("[DEBUG] Retry limit reached for feedback.")
                    return jsonify({"type": "final_message", "content": "I've tried my best. Let's start a new search!"})
                session['retries'] += 1
                session['conversation'] += f"\nUser was not satisfied. New request: {user_input}"
            else:
                 session['conversation'] += f"\nMy Answer: {user_input}"

        if data.get("distance"):
            session['travel_distance'] = int(data.get("distance"))
        if data.get('expand_search'):
            session['travel_distance'] = 20000

        print(f"[DEBUG] Session after input processing: {dict(session)}")
        llm_response = refine_query_with_llm(session['conversation'])
        print(f"[DEBUG] LLM response: {llm_response}")
        if llm_response.get("type") != "keyword":
            print("[DEBUG] LLM did not return a keyword, returning response.")
            return jsonify(llm_response)

        final_keyword = llm_response.get("content")
        session['last_keyword'] = final_keyword
        
        current_distance = session.get('travel_distance', 3000)
        print(f"[DEBUG] Calling get_nearby_places with location={location}, keyword={final_keyword}, distance={current_distance}")
        nearby_places = get_nearby_places(location, final_keyword, current_distance)
        print(f"[DEBUG] Nearby places: {nearby_places}")

        if not nearby_places or not nearby_places.get('results'):
            if current_distance < 20000:
                print("[DEBUG] No places found, suggesting to expand search.")
                return jsonify({"type": "expand_search", "message": "I couldn't find anything in that range. Would you like to expand the search area?"})
            else:
                print("[DEBUG] No places found even after expanding search.")
                return jsonify({"type": "error", "content": "I couldn't find any places, even in a wider area."})

        unseen_places = [p for p in nearby_places['results'] if p.get('place_id') not in session.get('excluded_ids', [])]
        print(f"[DEBUG] Unseen places: {unseen_places}")
        
        if not unseen_places:
            print("[DEBUG] No unseen places found.")
            return jsonify({"type": "error", "content": "I couldn't find any new places matching your refined search. Try broadening your criteria or starting a new search."})
        
        detailed_places = [get_place_details_and_photos(p.get('place_id')) for p in unseen_places[:10] if p.get('place_id')]
        print(f"[DEBUG] Detailed places: {detailed_places}")
        final_recs_data = get_final_recommendation(session['conversation'], [d for d in detailed_places if d], location)
        print(f"[DEBUG] Final recommendations data: {final_recs_data}")

        if not final_recs_data or not final_recs_data.get("recommendations"):
            print("[DEBUG] AI had trouble picking final recommendations.")
            return jsonify({"type": "error", "content": "The AI had trouble picking final recommendations. Please try again."})

        session['excluded_ids'].extend([p.get('place_id') for p in detailed_places if p])
        final_recs_data['last_keyword'] = final_keyword
        
        session.modified = True
        print(f"[DEBUG] Session before response: {dict(session)}")
        return jsonify({"type": "recommendation", "data": final_recs_data})
    except Exception as e:
        import traceback
        print(f"[ERROR] Exception in /get_recommendation: {e}")
        traceback.print_exc()
        return jsonify({"type": "error", "content": "An internal server error occurred. Please try again later."}), 500

@app.route("/history")
def history_page():
    return render_template("history.html")

if __name__ == "__main__":
    app.run(debug=True)
