document.addEventListener("DOMContentLoaded", () => {
    // State Containers
    const allStates = ["location", "distance", "loading", "results", "feedback", "error"];
    const containers = Object.fromEntries(allStates.map(id => [id, document.getElementById(`${id}-container`)]));

    // Interactive Elements
    const grantLocationButton = document.getElementById("grant-location-button");
    const distanceButtons = document.querySelectorAll(".distance-button");
    const initialQueryInput = document.getElementById("initial-query");
    const cardsWrapper = document.getElementById("cards-wrapper");
    const restartButton = document.getElementById("restart-button");
    const refineButton = document.getElementById("refine-button");
    const feedbackForm = document.getElementById("feedback-form");
    const feedbackInput = document.getElementById("feedback-input");
    const loadingText = document.getElementById("loading-text");
    const errorMessageText = document.getElementById("error-message");

    let userLocation = null;
    let lastSuccessfulKeyword = '';
    let loadingInterval;
    let currentDistance = null;

    // --- Engaging Loading Animation ---
    const loadingMessages = [ "Consulting local guides... 🗺️", "Analyzing vibes... ✨", "Finding hidden gems... 💎", "Crafting your recommendations... 🧑‍🍳", "Just a moment more..." ];
    function startLoadingAnimation() {
        let messageIndex = 0;
        loadingText.textContent = loadingMessages[messageIndex];
        loadingInterval = setInterval(() => { messageIndex = (messageIndex + 1) % loadingMessages.length; loadingText.textContent = loadingMessages[messageIndex]; }, 2500);
    }
    function stopLoadingAnimation() { clearInterval(loadingInterval); }

    // --- State Management ---
    function showState(state) {
        Object.values(containers).forEach(container => container.classList.remove("active"));
        containers[state].classList.add("active");
    }

    // --- Main Initialization ---
    function init() {
        if (!initialQueryInput.value) { window.location.href = "/"; return; }
        const storedLocation = localStorage.getItem('userLocation');
        if (storedLocation) {
            userLocation = JSON.parse(storedLocation);
            showState("distance");
        } else {
            showState("location");
        }
    }

    // --- API and Logic Flow ---
    function beginSearch() {
        const query = initialQueryInput.value;
        search(query, false);
    }

    async function search(query, isFeedback = false, expand = false) {
        showState("loading");
        startLoadingAnimation();
        try {
            const response = await fetch("/get_recommendation", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, location: userLocation, is_feedback: isFeedback, distance: currentDistance, expand }),
            });
            const data = await response.json();
            handleServerResponse(data);
        } catch (error) {
            errorMessageText.textContent = "An unexpected error occurred while connecting to the server.";
            showState("error");
        } finally {
            stopLoadingAnimation();
        }
    }
    
    // --- UI Rendering ---
    function handleServerResponse(data) {
        stopLoadingAnimation();
        if (data.type === "question") {
            showState("feedback");
            document.getElementById("chat-history").innerHTML = `<p>${data.content}</p>`;
            feedbackInput.focus();
        } else if (data.type === "recommendation") {
            if (data.data.message) { alert(data.data.message); }
            lastSuccessfulKeyword = data.data.last_keyword;
            saveSearchToHistory(data.data);
            displayRecommendationCards(data.data.recommendations);
            showState("results");
        } else if (data.type === "expand_search") {
            if (confirm(data.message)) {
                search(initialQueryInput.value, false, true);
            } else {
                window.location.href = "/";
            }
        } else if (data.type === "error" || data.type === "final_message") {
            alert(data.content);
            window.location.href = "/";
        }
    }

    function displayRecommendationCards(places) {
        cardsWrapper.innerHTML = "";
        const bookmarks = JSON.parse(localStorage.getItem('bookmarks')) || {};
        places.forEach((place, index) => {
            const card = document.createElement("div");
            card.className = "recommendation-card";
            card.style.animationDelay = `${index * 150}ms`;
            
            const mainPhoto = place.photo_urls.length > 0 ? place.photo_urls[0] : 'https://via.placeholder.com/350x200/181818/B3B3B3?text=No+Image';
            const reviewText = place.reviews && place.reviews.length > 0 && place.reviews[0].text ? `"${place.reviews[0].text}"` : 'No recent reviews available.';
            const isBookmarked = !!bookmarks[place.place_id];

            card.innerHTML = `
                <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" data-place-id="${place.place_id}">${isBookmarked ? '♥' : '♡'}</button>
                <img src="${mainPhoto}" alt="${place.name}" class="card-photo">
                <p class="travel-time">~ ${place.travel_time} away 🚗</p>
                <h3 class="card-title">${place.name}</h3>
                <p class="card-rating">⭐ ${place.rating || 'N/A'} (${place.user_ratings_total || 0} ratings)</p>
                <p class="card-review">${reviewText}</p>
                <a href="${place.link}" target="_blank" class="card-link">View on Map</a>
            `;
            cardsWrapper.appendChild(card);
            
            card.querySelector('.bookmark-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                toggleBookmark(place, e.currentTarget);
            });
        });
    }

    // --- LocalStorage Logic for Bookmarks & History ---
    function toggleBookmark(placeData, buttonElement) {
        const bookmarks = JSON.parse(localStorage.getItem('bookmarks')) || {};
        const placeId = placeData.place_id;

        if (bookmarks[placeId]) {
            delete bookmarks[placeId];
            buttonElement.classList.remove('bookmarked');
            buttonElement.innerHTML = '♡';
        } else {
            bookmarks[placeId] = placeData;
            buttonElement.classList.add('bookmarked');
            buttonElement.innerHTML = '♥';
        }
        localStorage.setItem('bookmarks', JSON.stringify(bookmarks));
    }

    function saveSearchToHistory(searchData) {
        let history = JSON.parse(localStorage.getItem('searchHistory')) || [];
        history = history.filter(item => item.last_keyword !== searchData.last_keyword);
        history.push(searchData);
        if (history.length > 10) history.shift();
        localStorage.setItem('searchHistory', JSON.stringify(history));
    }

    // --- Event Listeners ---
    grantLocationButton.addEventListener("click", () => {
        if (!userLocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    userLocation = { lat: position.coords.latitude, lng: position.coords.longitude };
                    localStorage.setItem('userLocation', JSON.stringify(userLocation));
                    showState("distance");
                },
                (error) => {
                    errorMessageText.textContent = "You denied location access. It's required to find places nearby.";
                    showState("error");
                }
            );
        } else {
            showState("distance");
        }
    });
    
    distanceButtons.forEach(button => {
        button.addEventListener("click", () => {
            currentDistance = button.dataset.distance;
            beginSearch();
        });
    });
    
    restartButton.addEventListener("click", () => { window.location.href = "/"; });

    refineButton.addEventListener("click", () => {
        showState("feedback");
        document.getElementById("chat-history").innerHTML = `<p>I see. We just searched for places matching: <strong>"${lastSuccessfulKeyword}"</strong>.</p><p>What should we adjust to find a better spot for you? 🤔</p>`;
        feedbackInput.focus();
    });

    feedbackForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const feedbackQuery = feedbackInput.value.trim();
        if (feedbackQuery) { search(feedbackQuery, true); }
        feedbackInput.value = "";
    });

    // --- Start the process ---
    init();
});
