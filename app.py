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
    print("--- [HELPER] Running moderation check...", flush=True)
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
        print(f"--- [HELPER] Moderation decision: {decision}", flush=True)
        return decision == "safe"
    except Exception as e:
        print(f"--- [CRITICAL_ERROR] Moderation check failed: {e}", flush=True)
        return False

def refine_query_with_llm(conversation_history):
    print("--- [HELPER] Refining query with LLM...", flush=True)
    system_prompt = "..." # Prompt removed for brevity, it's unchanged
    try:
        response = openai.chat.completions.create(model="gpt-4o-mini", response_format={"type": "json_object"}, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "..."}]) # User content removed for brevity
        result = json.loads(response.choices[0].message.content)
        print(f"--- [HELPER] LLM refinement result: {result}", flush=True)
        return result
    except Exception as e:
        print(f"--- [CRITICAL_ERROR] LLM query refinement failed: {e}", flush=True)
        return {"type": "error", "content": "Sorry, I had trouble refining your query."}

def get_nearby_places(location, keyword, radius):
    print(f"--- [HELPER] Searching Google Places API with keyword='{keyword}', radius='{radius}'", flush=True)
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {'location': f"{location['lat']},{location['lng']}", 'radius': radius, 'keyword': keyword, 'key': GOOGLE_MAPS_API_KEY}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        results = response.json()
        print(f"--- [HELPER] Google Places API found {len(results.get('results', []))} results.", flush=True)
        return results
    except Exception as e:
        print(f"--- [CRITICAL_ERROR] Google Places API search failed: {e}", flush=True)
        return None

# Other helper functions (get_place_details_and_photos, get_travel_times, get_final_recommendation) are unchanged.

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
        if not plan: return redirect(url_for('home'))
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
    print("\n\n--- [STEP 1] Received new recommendation request. ---", flush=True)
    data = request.json
    location = data.get("location")
    user_input = data.get("query")
    is_feedback = data.get("is_feedback", False)
    
    print(f"--- [STEP 2] Building conversation. Initial query: '{user_input}', Is feedback: {is_feedback}", flush=True)
    if 'conversation' not in session:
        if not moderate_query(user_input): 
            return jsonify({"type": "error", "content": "This search is not permitted."})
        session['conversation'] = f"User's initial request: {user_input}"
        session['excluded_ids'] = []
        session['retries'] = 0
    else:
        # This block is for refining a search, unchanged.
        if is_feedback:
            if not moderate_query(user_input): return jsonify({"type": "error", "content": "This search is not permitted."})
            if session.get('retries', 0) >= 2: return jsonify({"type": "final_message", "content": "I've tried my best. Let's start a new search!"})
            session['retries'] += 1
            session['conversation'] += f"\nUser was not satisfied. New request: {user_input}"
        else:
             session['conversation'] += f"\nMy Answer: {user_input}"
    
    print("--- [STEP 3] Updating travel distance.", flush=True)
    if data.get("distance"): session['travel_distance'] = int(data.get("distance"))
    if data.get('expand_search'): session['travel_distance'] = 20000

    print("--- [STEP 4] Refining query with LLM.", flush=True)
    llm_response = refine_query_with_llm(session['conversation'])
    if llm_response.get("type") != "keyword":
        print("--- [INFO] LLM asked a clarifying question. Responding to user.", flush=True)
        return jsonify(llm_response)

    final_keyword = llm_response.get("content")
    session['last_keyword'] = final_keyword
    print(f"--- [STEP 5] Refined keyword is: '{final_keyword}'", flush=True)
    
    current_distance = session.get('travel_distance', 3000)
    print(f"--- [STEP 6] Searching Google Places with radius: {current_distance}", flush=True)
    nearby_places = get_nearby_places(location, final_keyword, current_distance)

    if not nearby_places or not nearby_places.get('results'):
        print("--- [INFO] No places found in initial search.", flush=True)
        if current_distance < 20000:
            return jsonify({"type": "expand_search", "message": "I couldn't find anything in that range. Would you like to expand the search area?"})
        else:
            return jsonify({"type": "error", "content": "I couldn't find any places, even in a wider area."})

    print(f"--- [STEP 7] Found {len(nearby_places.get('results', []))} total places. Filtering out previously seen places.", flush=True)
    unseen_places = [p for p in nearby_places['results'] if p.get('place_id') not in session.get('excluded_ids', [])]
    
    if not unseen_places:
        print("--- [INFO] No *new* places found after filtering.", flush=True)
        return jsonify({"type": "error", "content": "I couldn't find any new places matching your refined search. Try broadening your criteria or starting a new search."})
    
    print(f"--- [STEP 8] Fetching details for up to 15 unseen places.", flush=True)
    detailed_places_list = [get_place_details_and_photos(p.get('place_id')) for p in unseen_places[:15] if p.get('place_id')]
    detailed_places = [d for d in detailed_places_list if d] # Filter out any None results from failed calls
    print(f"--- [STEP 9] Successfully fetched details for {len(detailed_places)} places.", flush=True)

    print("--- [STEP 10] Sending place data to LLM for final ranking.", flush=True)
    final_recs_data = get_final_recommendation(session['conversation'], detailed_places, location)

    if not final_recs_data or not final_recs_data.get("recommendations"):
        print("--- [ERROR] Final recommendation ranking from LLM failed or returned empty.", flush=True)
        return jsonify({"type": "error", "content": "The AI had trouble picking final recommendations. Please try again."})

    session['excluded_ids'].extend([p.get('place_id') for p in detailed_places if p])
    final_recs_data['last_keyword'] = final_keyword
    
    session.modified = True
    print("--- [STEP 11] Successfully generated recommendations. Sending response to user.", flush=True)
    return jsonify({"type": "recommendation", "data": final_recs_data})

@app.route("/history")
def history_page():
    return render_template("history.html")

if __name__ == "__main__":
    app.run(debug=True)
