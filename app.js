// Mood Travel App - Complete JavaScript
let app = {
    apiBase: '/api',
    token: localStorage.getItem('token'),
    currentUser: null,
    settings: {
        destinationsPerPage: 24,
        filteredDestinationsPerPage: 80,
        festivalsPerCountry: 9
    },

    init() {
        this.setupEventListeners();
        this.loadDestinations();
        this.loadFestivals();
        this.checkAuthStatus();
        this.setupMoodAnalyzer();
    },

    setupEventListeners() {
        // Mood analysis form
        const moodForm = document.getElementById('moodForm');
        if (moodForm) {
            moodForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.analyzeMood();
            });
        }

        // Login form
        const loginForm = document.getElementById('loginForm');
        if (loginForm) {
            loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.login();
            });
        }

        // Register form
        const registerForm = document.getElementById('registerForm');
        if (registerForm) {
            registerForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.register();
            });
        }

        // Search functionality
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.searchDestinations(e.target.value);
            });
        }
        
        // Country filter functionality
        this.setupCountryFilter();
        
        // Mood analyzer enhancements
        this.setupMoodAnalyzer();
    },
    
    setupMoodAnalyzer() {
        // Setup mood emoji interactions
        const moodEmojis = document.querySelectorAll('.mood-emoji');
        moodEmojis.forEach(emoji => {
            emoji.addEventListener('click', () => {
                // Remove active class from all emojis
                moodEmojis.forEach(e => e.classList.remove('active'));
                // Add active class to clicked emoji
                emoji.classList.add('active');
                
                // Set the mood text based on selection
                const moodText = document.getElementById('moodText');
                if (moodText) {
                    const mood = emoji.dataset.mood;
                    const moodDescriptions = {
                        'happy': 'I\'m feeling happy and cheerful today! I want to experience joy and positive vibes.',
                        'excited': 'I\'m feeling excited and energetic! I want adventure and thrilling experiences.',
                        'relaxed': 'I\'m feeling relaxed and peaceful. I need a calm and serene environment.',
                        'adventurous': 'I\'m feeling adventurous and bold! I want to explore new places and try new things.',
                        'romantic': 'I\'m feeling romantic and dreamy. I want intimate and beautiful experiences.',
                        'curious': 'I\'m feeling curious and interested. I want to learn and discover new cultures.',
                        'stressed': 'I\'m feeling stressed and need a break. I want relaxation and peace.',
                        'energetic': 'I\'m feeling energetic and active! I want dynamic and engaging activities.'
                    };
                    moodText.value = moodDescriptions[mood] || '';
                }
            });
        });
        
        // Setup mood option cards
        const moodOptionCards = document.querySelectorAll('.mood-option-card');
        moodOptionCards.forEach(card => {
            card.addEventListener('click', () => {
                // Remove selected class from all cards
                moodOptionCards.forEach(c => c.classList.remove('selected'));
                // Add selected class to clicked card
                card.classList.add('selected');
                
                // Check the radio button
                const radio = card.querySelector('.mood-radio');
                if (radio) {
                    radio.checked = true;
                }
            });
        });
    },

    async login() {
        console.log('Login function called');
        const email = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;

        console.log('Login form values:', { email, password: password ? '***' : 'empty' });

        if (!email || !password) {
            this.showNotification('Please fill in all fields.', 'warning');
            return;
        }

        try {
            console.log('Sending login request to:', `${this.apiBase}/auth/login`);
            const response = await fetch(`${this.apiBase}/auth/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ email, password })
            });

            console.log('Login response status:', response.status);
            const data = await response.json();
            console.log('Login response data:', data);

            if (response.ok) {
                this.token = data.token || 'session-token';
                this.currentUser = data.user;
                localStorage.setItem('token', this.token);
                localStorage.setItem('user', JSON.stringify(data.user));
                
                this.showNotification('Login successful!', 'success');
                this.updateUIAfterAuth();
                
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('loginModal'));
                if (modal) modal.hide();
            } else {
                this.showNotification(data.error || 'Login failed', 'error');
            }
        } catch (error) {
            console.error('Login error:', error);
            this.showNotification('An error occurred during login.', 'error');
        }
    },

    async register() {
        console.log('Registration function called');
        const name = document.getElementById('registerName').value;
        const email = document.getElementById('registerEmail').value;
        const password = document.getElementById('registerPassword').value;

        console.log('Form values:', { name, email, password: password ? '***' : 'empty' });

        if (!name || !email || !password) {
            this.showNotification('Please fill in all fields.', 'warning');
            return;
        }

        try {
            console.log('Sending registration request to:', `${this.apiBase}/auth/register`);
            const response = await fetch(`${this.apiBase}/auth/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ name, email, password })
            });

            console.log('Registration response status:', response.status);
            const data = await response.json();
            console.log('Registration response data:', data);

            if (response.ok) {
                this.showNotification('Registration successful! Please login.', 'success');
                
                // Close modal and show login
                const registerModal = bootstrap.Modal.getInstance(document.getElementById('registerModal'));
                if (registerModal) registerModal.hide();
                
                setTimeout(() => {
                    const loginModal = new bootstrap.Modal(document.getElementById('loginModal'));
                    loginModal.show();
                }, 1000);
            } else {
                this.showNotification(data.error || 'Registration failed', 'error');
            }
        } catch (error) {
            console.error('Registration error:', error);
            this.showNotification('An error occurred during registration.', 'error');
        }
    },

    logout() {
        this.token = null;
        this.currentUser = null;
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        this.updateUIAfterAuth();
        this.showNotification('Logged out successfully!', 'success');
    },

    checkAuthStatus() {
        // Load saved user from localStorage if available
        try {
            const savedUser = localStorage.getItem('user');
            if (savedUser && !this.currentUser) {
                this.currentUser = JSON.parse(savedUser);
            }
        } catch (e) {}

        if (!this.token) {
            this.token = localStorage.getItem('token');
        }

        if (this.currentUser) {
            this.updateUIAfterAuth();
        }
    },

    updateUIAfterAuth() {
        const authButtons = document.querySelectorAll('.auth-buttons');
        const userInfo = document.querySelectorAll('.user-info');
        const logoutBtn = document.querySelectorAll('.logout-btn');

        if (this.currentUser) {
            // Show user info, hide auth buttons
            authButtons.forEach(btn => btn.style.display = 'none');
            userInfo.forEach(info => {
                info.style.display = 'block';
                info.innerHTML = `
                    <span class="text-white me-3">Welcome, ${this.currentUser.username || this.currentUser.first_name || 'Traveler'}!</span>
                    <button class="btn btn-outline-light btn-sm" onclick="app.logout()">Logout</button>
                `;
            });
        } else {
            // Show auth buttons, hide user info
            authButtons.forEach(btn => btn.style.display = 'block');
            userInfo.forEach(info => info.style.display = 'none');
        }
    },

    async analyzeMood() {
        const moodText = document.getElementById('moodText').value;
        const selectedMood = document.querySelector('input[name="moodSelect"]:checked')?.value;
        const textInput = moodText || selectedMood || '';

        if (!textInput) {
            this.showNotification('Please enter text or select a mood.', 'warning');
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/mood/analyze`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.token ? `Bearer ${this.token}` : ''
                },
                body: JSON.stringify({ text: textInput })
            });

            const data = await response.json();

            const moodResultDiv = document.getElementById('moodResult');
            const moodAnalysisContent = document.getElementById('moodAnalysisContent');

            if (response.ok) {
                // Backend returns { mood, intensity } under mood_analysis
                const moodType = (data.mood_analysis?.mood || 'neutral');
                const intensityVal = (data.mood_analysis?.intensity ?? 0);
                const intensityPct = Math.round(intensityVal * 100);
                const travel_recommendations = data.travel_recommendations;
                
                moodAnalysisContent.innerHTML = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Detected Mood: <span class="badge bg-primary">${moodType.charAt(0).toUpperCase() + moodType.slice(1)}</span></h6>
                        </div>
                        <div class="col-md-6">
                            <h6>Intensity: <span class="badge bg-secondary">${intensityPct}%</span></h6>
                        </div>
                    </div>
                    <p>Based on your input: "${textInput}"</p>
                `;
                moodResultDiv.style.display = 'block';
                
                // Display travel recommendations immediately
                if (travel_recommendations) {
                    this.displayTravelRecommendations(travel_recommendations, moodType);
                }
                
                // Also get detailed destination recommendations
                this.getRecommendations(moodType);
                
                this.showNotification('Mood analyzed! Travel recommendations ready!', 'success');
            } else {
                moodAnalysisContent.innerHTML = `<p class="text-danger">${data.error || 'Failed to analyze mood.'}</p>`;
                moodResultDiv.style.display = 'block';
                this.showNotification(data.error || 'Mood analysis failed', 'error');
            }
        } catch (error) {
            console.error('Error analyzing mood:', error);
            this.showNotification('An error occurred during mood analysis.', 'error');
        }
    },

    async getRecommendations(mood) {
        try {
            const response = await fetch(`${this.apiBase}/recommendations`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': this.token ? `Bearer ${this.token}` : ''
                },
                body: JSON.stringify({ mood: mood })
            });

            const data = await response.json();

            if (response.ok) {
                this.displayRecommendations(data.recommendations, mood);
            } else {
                this.showNotification('Failed to get recommendations.', 'error');
            }
        } catch (error) {
            console.error('Error getting recommendations:', error);
            this.showNotification('An error occurred while getting recommendations.', 'error');
        }
    },

    displayRecommendations(recommendations, mood) {
        const recommendationsDiv = document.getElementById('recommendations');
        if (!recommendationsDiv) return;

        let html = `
            <div class="row">
                <div class="col-12">
                    <h3 class="mb-4">Travel Recommendations for your ${mood} mood</h3>
                </div>
            </div>
            <div class="row">
        `;

        recommendations.forEach(rec => {
            const dest = rec.destination;
            // Use image_url if available, otherwise fallback to images array or placeholder
            const imageUrl = dest.image_url || (dest.images && dest.images.length > 0 ? dest.images[0] : null) || 'https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80';
            
            html += `
                <div class="col-lg-4 col-md-6 mb-4">
                    <div class="card h-100 shadow-sm">
                        <img src="${imageUrl}" 
                             class="card-img-top" alt="${dest.name}" 
                             style="height: 200px; object-fit: cover;"
                             onerror="this.src='https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80'">
                        <div class="card-body">
                            <h5 class="card-title">${dest.name}</h5>
                            <p class="card-text text-muted">${dest.city}, ${dest.country}</p>
                            <p class="card-text">${dest.description || 'Explore this amazing destination!'}</p>
                            <div class="d-flex justify-content-between align-items-center">
                                <div class="rating">
                                    <span class="text-warning">★</span>
                                    <span>${dest.ratings.overall}</span>
                                </div>
                                <button class="btn btn-primary btn-sm" onclick="app.viewDestination(${dest.id})">
                                    View Details
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        recommendationsDiv.innerHTML = html;
        recommendationsDiv.scrollIntoView({ behavior: 'smooth' });
    },

    displayTravelRecommendations(recommendations, mood) {
        const recommendationsDiv = document.getElementById('travelRecommendations');
        const recommendationsContent = document.getElementById('recommendationsContent');
        
        if (!recommendationsDiv || !recommendationsContent) return;

        let html = `
            <div class="row mb-4">
                <div class="col-12">
                    <h6 class="text-primary mb-2">🎯 Travel Style: <span class="badge bg-info">${recommendations.travel_style}</span></h6>
                    <p class="mb-3">${recommendations.description}</p>
                </div>
            </div>
            
            <div class="row mb-4">
                <div class="col-md-6">
                    <h6 class="text-success mb-3"><i class="fas fa-map-marker-alt me-2"></i>Recommended Destinations</h6>
                    <div class="list-group">
                        ${recommendations.destinations.map(dest => 
                            `<div class="list-group-item list-group-item-action">
                                <i class="fas fa-plane me-2 text-primary"></i>${dest}
                            </div>`
                        ).join('')}
                    </div>
                </div>
                <div class="col-md-6">
                    <h6 class="text-warning mb-3"><i class="fas fa-hiking me-2"></i>Recommended Activities</h6>
                    <div class="list-group">
                        ${recommendations.activities.map(activity => 
                            `<div class="list-group-item list-group-item-action">
                                <i class="fas fa-star me-2 text-warning"></i>${activity}
                            </div>`
                        ).join('')}
                    </div>
                </div>
            </div>
            
            <div class="text-center">
                <button class="btn btn-primary btn-lg" onclick="showDestinations()">
                    <i class="fas fa-search me-2"></i>Explore These Destinations
                </button>
            </div>
        `;

        recommendationsContent.innerHTML = html;
        recommendationsDiv.style.display = 'block';
    },

    setupCountryFilter() {
        const filterButtons = document.querySelectorAll('#countryFilter button');
        filterButtons.forEach(button => {
            button.addEventListener('click', () => {
                // Remove active class from all buttons
                filterButtons.forEach(btn => btn.classList.remove('active'));
                // Add active class to clicked button
                button.classList.add('active');
                
                const country = button.dataset.country;
                this.filterDestinationsByCountry(country);
            });
        });
    },

    async filterDestinationsByCountry(country) {
        if (country === 'all') {
            this.loadDestinations();
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/destinations?per_page=${this.settings.filteredDestinationsPerPage}`);
            const data = await response.json();

            if (response.ok) {
                const filteredDestinations = data.destinations.filter(dest => {
                    const destCountry = dest.country || '';
                    return destCountry.toLowerCase().includes(country.toLowerCase());
                });
                this.displayDestinations(filteredDestinations);
            }
        } catch (error) {
            console.error('Error filtering destinations:', error);
        }
    },

    async loadDestinations() {
        try {
            const response = await fetch(`${this.apiBase}/destinations?per_page=${this.settings.destinationsPerPage}`);
            const data = await response.json();

            if (response.ok) {
                this.displayDestinations(data.destinations);
            } else {
                console.error('Failed to load destinations');
            }
        } catch (error) {
            console.error('Error loading destinations:', error);
        }
    },

    displayDestinations(destinations) {
        const destinationsDiv = document.getElementById('destinationsList');
        if (!destinationsDiv) return;

        let html = '<div class="row">';

        destinations.forEach(dest => {
            // Use a better fallback image and add error handling
            const imageUrl = dest.image_url || 'https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80';
            
            html += `
                <div class="col-lg-4 col-md-6 mb-4">
                    <div class="card h-100 shadow-sm">
                        <img src="${imageUrl}" 
                             class="card-img-top" alt="${dest.name}" 
                             style="height: 200px; object-fit: cover;"
                             onerror="this.src='https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80'">
                        <div class="card-body">
                            <h5 class="card-title">${dest.name}</h5>
                            <p class="card-text text-muted">
                                <i class="fas fa-map-marker-alt me-1"></i>${dest.city}, ${dest.country}
                            </p>
                            <p class="card-text">${dest.description || 'Explore this amazing destination!'}</p>
                            <div class="mb-2">
                                <span class="badge bg-primary me-1">${dest.climate || 'Various'}</span>
                                <span class="badge bg-success me-1">${dest.best_time_to_visit || 'Year-round'}</span>
                                <span class="badge bg-info">${dest.average_cost || 'Moderate'}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <div class="rating text-muted">
                                    <span class="text-warning">★</span> ${dest.ratings?.overall || 4.7}
                                </div>
                                <div class="btn-group" role="group">
                                    <button class="btn btn-primary btn-sm" onclick="app.viewDestination(${dest.id})">
                                        <i class="fas fa-info-circle me-1"></i>Details
                                    </button>
                                    <button class="btn btn-outline-primary btn-sm" onclick="app.viewAttractions(${dest.id})">
                                        <i class="fas fa-landmark me-1"></i>Attractions
                                    </button>
                                    <button class="btn btn-outline-success btn-sm" onclick="app.viewFestivals(${dest.id})">
                                        <i class="fas fa-calendar me-1"></i>Festivals
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        destinationsDiv.innerHTML = html;
    },

    async loadFestivals() {
        try {
            const response = await fetch(`${this.apiBase}/upcoming-festivals`);
            const data = await response.json();

            if (response.ok) {
                this.displayFestivals(data.festivals || data);
            } else {
                console.error('Failed to load festivals');
            }
        } catch (error) {
            console.error('Error loading festivals:', error);
        }
    },

    displayFestivals(festivals) {
        const festivalsDiv = document.getElementById('festivalsList');
        if (!festivalsDiv) return;

        // Group festivals by country
        const festivalsByCountry = {};
        festivals.forEach(festival => {
            const country = festival.country || festival.location || 'Various Countries';
            if (!festivalsByCountry[country]) {
                festivalsByCountry[country] = [];
            }
            festivalsByCountry[country].push(festival);
        });

        let html = '';

        // Display festivals grouped by country
        Object.keys(festivalsByCountry).forEach(country => {
            const countryFestivals = festivalsByCountry[country];
            
            html += `
                <div class="country-festivals mb-5">
                    <div class="row">
                        <div class="col-12">
                            <h3 class="country-title mb-4">
                                <i class="fas fa-flag me-2"></i>${country}
                                <span class="badge bg-primary ms-2">${countryFestivals.length} Festival${countryFestivals.length > 1 ? 's' : ''}</span>
                            </h3>
                        </div>
                    </div>
                    <div class="row">
            `;

            // Display festivals for this country
            const maxFestivals = this.settings?.festivalsPerCountry || countryFestivals.length;
            countryFestivals.slice(0, maxFestivals).forEach(festival => {
                const imageUrl = festival.image_url || festival.images?.[0] || 'https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80';
                
                html += `
                    <div class="col-lg-4 col-md-6 mb-4">
                        <div class="card h-100 shadow-sm">
                            <img src="${imageUrl}" 
                                 class="card-img-top" alt="${festival.name}" 
                                 style="height: 200px; object-fit: cover;"
                                 onerror="this.src='https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80'">
                            <div class="card-body">
                                <h5 class="card-title">${festival.name}</h5>
                                <p class="card-text text-muted">
                                    <i class="fas fa-map-marker-alt me-1"></i>${festival.location || festival.city || country}
                                </p>
                                <p class="card-text">${festival.description || 'Experience this amazing festival!'}</p>
                                <div class="d-flex justify-content-between align-items-center">
                                    <div class="text-muted">
                                        <i class="fas fa-calendar me-1"></i>
                                        ${festival.date || festival.month || 'Upcoming'}
                                    </div>
                                    <button class="btn btn-outline-primary btn-sm" onclick="app.viewFestivals(${festival.destination_id || 1})">
                                        <i class="fas fa-calendar-alt me-1"></i>More Info
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            });

            html += `
                    </div>
                    ${countryFestivals.length > maxFestivals ? `
                        <div class="text-center mt-3">
                            <button class="btn btn-outline-secondary btn-sm" onclick="app.showAllCountryFestivals('${country}', ${JSON.stringify(countryFestivals).replace(/"/g, '&quot;')})">
                                <i class="fas fa-eye me-1"></i>View All ${country} Festivals (${countryFestivals.length})
                            </button>
                        </div>
                    ` : ''}
                </div>
            `;
        });

        festivalsDiv.innerHTML = html;
    },

    showAllCountryFestivals(country, festivals) {
        const festivalsDiv = document.getElementById('festivalsList');
        if (!festivalsDiv) return;

        let html = `
            <div class="country-festivals mb-5">
                <div class="row">
                    <div class="col-12">
                        <div class="d-flex justify-content-between align-items-center mb-4">
                            <h3 class="country-title mb-0">
                                <i class="fas fa-flag me-2"></i>${country}
                                <span class="badge bg-primary ms-2">${festivals.length} Festival${festivals.length > 1 ? 's' : ''}</span>
                            </h3>
                            <button class="btn btn-outline-secondary btn-sm" onclick="app.loadFestivals()">
                                <i class="fas fa-arrow-left me-1"></i>Back to All Countries
                            </button>
                        </div>
                    </div>
                </div>
                <div class="row">
        `;

        // Display all festivals for this country
        festivals.forEach(festival => {
            const imageUrl = festival.image_url || festival.images?.[0] || 'https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80';
            
            html += `
                <div class="col-lg-4 col-md-6 mb-4">
                    <div class="card h-100 shadow-sm">
                        <img src="${imageUrl}" 
                             class="card-img-top" alt="${festival.name}" 
                             style="height: 200px; object-fit: cover;"
                             onerror="this.src='https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80'">
                        <div class="card-body">
                            <h5 class="card-title">${festival.name}</h5>
                            <p class="card-text text-muted">
                                <i class="fas fa-map-marker-alt me-1"></i>${festival.location || festival.city || country}
                            </p>
                            <p class="card-text">${festival.description || 'Experience this amazing festival!'}</p>
                            <div class="d-flex justify-content-between align-items-center">
                                <div class="text-muted">
                                    <i class="fas fa-calendar me-1"></i>
                                    ${festival.date || festival.month || 'Upcoming'}
                                </div>
                                <button class="btn btn-outline-primary btn-sm" onclick="app.viewFestivals(${festival.destination_id || 1})">
                                    <i class="fas fa-calendar-alt me-1"></i>More Info
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += `
                </div>
            </div>
        `;

        festivalsDiv.innerHTML = html;
    },

    async loadMoreFestivals() {
        try {
            const response = await fetch(`${this.apiBase}/upcoming-festivals`);
            const data = await response.json();

            if (response.ok) {
                this.displayAllFestivals(data.festivals || data);
            }
        } catch (error) {
            console.error('Error loading more festivals:', error);
        }
    },

    displayAllFestivals(festivals) {
        const festivalsDiv = document.getElementById('festivalsList');
        if (!festivalsDiv) return;

        let html = '<div class="row">';

        festivals.forEach(festival => {
            const imageUrl = festival.image_url || festival.images?.[0] || 'https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80';
            
            html += `
                <div class="col-lg-4 col-md-6 mb-4">
                    <div class="card h-100 shadow-sm">
                        <img src="${imageUrl}" 
                             class="card-img-top" alt="${festival.name}" 
                             style="height: 200px; object-fit: cover;"
                             onerror="this.src='https://images.unsplash.com/photo-1469474968028-56623f02e42e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&q=80'">
                        <div class="card-body">
                            <h5 class="card-title">${festival.name}</h5>
                            <p class="card-text text-muted">
                                <i class="fas fa-map-marker-alt me-1"></i>${festival.location || festival.country || 'Various Locations'}
                            </p>
                            <p class="card-text">${festival.description || 'Experience this amazing festival!'}</p>
                            <div class="d-flex justify-content-between align-items-center">
                                <div class="text-muted">
                                    <i class="fas fa-calendar me-1"></i>
                                    ${festival.date || festival.month || 'Upcoming'}
                                </div>
                                <button class="btn btn-outline-primary btn-sm" onclick="app.viewFestivals(${festival.destination_id || 1})">
                                    <i class="fas fa-calendar-alt me-2"></i>More Info
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        festivalsDiv.innerHTML = html;
    },

    async searchDestinations(query) {
        if (!query.trim()) {
            this.loadDestinations();
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/destinations?search=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (response.ok) {
                this.displayDestinations(data.destinations);
            }
        } catch (error) {
            console.error('Error searching destinations:', error);
        }
    },

    // Navigation functions for different pages
    viewDestination(id) {
        window.location.href = `/destination/${id}`;
    },

    viewAttractions(id) {
        window.location.href = `/attractions/${id}`;
    },

    viewFestivals(id) {
        window.location.href = `/festivals/${id}`;
    },

    viewMap(id) {
        window.location.href = `/map/${id}`;
    },

    viewWeather(id) {
        window.location.href = `/weather/${id}`;
    },

    async viewDestinationModal(id) {
        try {
            const response = await fetch(`${this.apiBase}/destinations/${id}`);
            const destination = await response.json();

            if (response.ok) {
                this.showDestinationModal(destination);
            } else {
                this.showNotification('Failed to load destination details.', 'error');
            }
        } catch (error) {
            console.error('Error viewing destination:', error);
            this.showNotification('An error occurred while loading destination details.', 'error');
        }
    },

    showDestinationModal(destination) {
        const modal = new bootstrap.Modal(document.getElementById('destinationModal'));
        const modalBody = document.getElementById('destinationModalBody');
        
        modalBody.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <img src="${destination.images ? destination.images[0] : 'https://via.placeholder.com/400x300'}" 
                         class="img-fluid rounded" alt="${destination.name}">
                </div>
                <div class="col-md-6">
                    <h4>${destination.name}</h4>
                    <p class="text-muted">${destination.city}, ${destination.country}</p>
                    <p>${destination.description}</p>
                    <div class="mb-3">
                        <strong>Travel Styles:</strong>
                        ${destination.travel_styles.map(style => `<span class="badge bg-secondary me-1">${style}</span>`).join('')}
                    </div>
                    <div class="mb-3">
                        <strong>Rating:</strong>
                        <span class="text-warning">★</span>
                        <span>${destination.ratings.overall}</span>
                    </div>
                    <div class="d-grid gap-2">
                        <button class="btn btn-primary" onclick="app.viewDestination(${destination.id})">
                            <i class="fas fa-info-circle me-2"></i>View Full Details
                        </button>
                        <button class="btn btn-outline-primary" onclick="app.viewAttractions(${destination.id})">
                            <i class="fas fa-landmark me-2"></i>See Attractions
                        </button>
                        <button class="btn btn-outline-success" onclick="app.viewFestivals(${destination.id})">
                            <i class="fas fa-calendar me-2"></i>View Festivals
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        modal.show();
    },

    async estimateBudget(destinationId) {
        try {
            const response = await fetch(`${this.apiBase}/budget/estimate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    destination_id: destinationId,
                    duration: 7,
                    group_size: 2,
                    accommodation_type: 'mid'
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.showDetailedBudget(data);
            } else {
                this.showNotification('Failed to estimate budget.', 'error');
            }
        } catch (error) {
            console.error('Error estimating budget:', error);
            this.showNotification('An error occurred while estimating budget.', 'error');
        }
    },

    showDetailedBudget(budgetData) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Budget Estimate for ${budgetData.destination}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Accommodation</h6>
                                <p>${budgetData.currency} ${budgetData.accommodation.cost}</p>
                                <small class="text-muted">${budgetData.accommodation.hotels.length} hotel options available</small>
                            </div>
                            <div class="col-md-6">
                                <h6>Food</h6>
                                <p>${budgetData.currency} ${budgetData.food.cost}</p>
                                <small class="text-muted">Daily budget: ${budgetData.currency} ${budgetData.food.daily_budget}</small>
                            </div>
                        </div>
                        <div class="row mt-3">
                            <div class="col-md-6">
                                <h6>Transport</h6>
                                <p>${budgetData.currency} ${budgetData.transport.cost}</p>
                            </div>
                            <div class="col-md-6">
                                <h6>Activities</h6>
                                <p>${budgetData.currency} ${budgetData.activities.cost}</p>
                            </div>
                        </div>
                        <div class="row mt-3">
                            <div class="col-md-6">
                                <h6>Additional Costs</h6>
                                <p>Visa: ${budgetData.currency} ${budgetData.additional.visa}</p>
                                <p>Insurance: ${budgetData.currency} ${budgetData.additional.insurance}</p>
                            </div>
                            <div class="col-md-6">
                                <h6>Total</h6>
                                <h4>${budgetData.currency} ${budgetData.total}</h4>
                                <small class="text-muted">Per person: ${budgetData.currency} ${budgetData.per_person}</small>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    async generatePackingList(destinationId) {
        try {
            const response = await fetch(`${this.apiBase}/packing/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    destination_id: destinationId,
                    activities: [{ type: 'hiking' }, { type: 'cultural' }],
                    duration: 7,
                    season: this.getCurrentSeason()
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.showDetailedPackingList(data);
            } else {
                this.showNotification('Failed to generate packing list.', 'error');
            }
        } catch (error) {
            console.error('Error generating packing list:', error);
            this.showNotification('An error occurred while generating packing list.', 'error');
        }
    },

    showDetailedPackingList(packingData) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-xl">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Packing List for ${packingData.destination}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <strong>Country:</strong> ${packingData.country}<br>
                                <strong>Duration:</strong> ${packingData.duration} days<br>
                                <strong>Season:</strong> ${packingData.season}
                            </div>
                            <div class="col-md-6">
                                <strong>Temperature Range:</strong> ${packingData.temperature_range.min}°C - ${packingData.temperature_range.max}°C
                            </div>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Essentials</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.essentials.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                                
                                <h6>Documents</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.documents.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                                
                                <h6>Electronics</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.electronics.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                            </div>
                            <div class="col-md-6">
                                <h6>Clothing</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.clothing.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                                
                                <h6>Toiletries</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.toiletries.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                                
                                <h6>Country-Specific Items</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.country_specific.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                            </div>
                        </div>
                        
                        ${packingData.packing_list.activity_specific.length > 0 ? `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Activity-Specific Items</h6>
                                <ul class="list-unstyled">
                                    ${packingData.packing_list.activity_specific.map(item => `<li><i class="fas fa-check text-success me-2"></i>${item}</li>`).join('')}
                                </ul>
                            </div>
                        </div>
                        ` : ''}
                        
                        <div class="row mt-3">
                            <div class="col-12">
                                <div class="alert alert-info">
                                    <h6>Special Notes:</h6>
                                    <p>${packingData.special_notes}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    getCurrentSeason() {
        const month = new Date().getMonth();
        if (month >= 2 && month <= 4) return 'Spring';
        if (month >= 5 && month <= 7) return 'Summer';
        if (month >= 8 && month <= 10) return 'Autumn';
        return 'Winter';
    },

    async searchFlights(fromCity, toCity, departDate, returnDate, passengers) {
        try {
            const response = await fetch(`${this.apiBase}/flights/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    from_city: fromCity,
                    to_city: toCity,
                    depart_date: departDate,
                    return_date: returnDate,
                    passengers: passengers
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.showFlightResults(data.flights);
            } else {
                this.showNotification('Failed to search flights.', 'error');
            }
        } catch (error) {
            console.error('Error searching flights:', error);
            this.showNotification('An error occurred while searching flights.', 'error');
        }
    },

    showFlightResults(flights) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-xl">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Flight Search Results</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${flights.length === 0 ? `
                            <div class="text-center py-5">
                                <i class="fas fa-plane fa-3x text-muted mb-3"></i>
                                <h4>No flights found</h4>
                                <p class="text-muted">Try different dates or routes</p>
                            </div>
                        ` : `
                            <div class="row">
                                ${flights.map(flight => `
                                    <div class="col-12 mb-3">
                                        <div class="card">
                                            <div class="card-body">
                                                <div class="row align-items-center">
                                                    <div class="col-md-2">
                                                        <div class="text-center">
                                                            <div class="h4 mb-1">${flight.airline_logo}</div>
                                                            <small class="text-muted">${flight.airline}</small>
                                                        </div>
                                                    </div>
                                                    <div class="col-md-3">
                                                        <div><strong>${flight.departure_time}</strong></div>
                                                        <small class="text-muted">${flight.departure_airport}</small>
                                                    </div>
                                                    <div class="col-md-3">
                                                        <div><strong>${flight.arrival_time}</strong></div>
                                                        <small class="text-muted">${flight.arrival_airport}</small>
                                                    </div>
                                                    <div class="col-md-2">
                                                        <div>${flight.duration}</div>
                                                        <small class="text-muted">${flight.flight_type}</small>
                                                    </div>
                                                    <div class="col-md-2">
                                                        <div class="text-success"><strong>$${flight.price}</strong></div>
                                                        <small class="text-muted">${flight.available_seats} seats left</small>
                                                        <div class="d-grid gap-2 mt-2">
                                                            <button class="btn btn-primary btn-sm" onclick="this.showFlightDetails('${flight.id}')">
                                                                <i class="fas fa-info-circle me-1"></i>Details
                                                            </button>
                                                            <button class="btn btn-success btn-sm" onclick="this.bookFlight('${flight.id}')">
                                                                <i class="fas fa-ticket-alt me-1"></i>Book Now
                                                            </button>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        `}
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    async showFlightDetails(flightId) {
        try {
            const response = await fetch(`${this.apiBase}/flights/details/${flightId}`);
            const flightDetails = await response.json();

            if (response.ok) {
                this.displayFlightDetails(flightDetails);
            } else {
                this.showNotification('Failed to get flight details.', 'error');
            }
        } catch (error) {
            console.error('Error getting flight details:', error);
            this.showNotification('An error occurred while getting flight details.', 'error');
        }
    },

    displayFlightDetails(flightDetails) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Flight Details - ${flightDetails.flight_id}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6><i class="fas fa-plane me-2"></i>Airline Information</h6>
                                <p><strong>Name:</strong> ${flightDetails.airline_info.name}</p>
                                <p><strong>Code:</strong> ${flightDetails.airline_info.code}</p>
                                <p><strong>Website:</strong> <a href="${flightDetails.airline_info.website}" target="_blank">${flightDetails.airline_info.website}</a></p>
                                <p><strong>Phone:</strong> ${flightDetails.airline_info.phone}</p>
                            </div>
                            <div class="col-md-6">
                                <h6><i class="fas fa-route me-2"></i>Route Information</h6>
                                <p><strong>Departure:</strong> ${flightDetails.route_info.departure.airport} (Terminal ${flightDetails.route_info.departure.terminal})</p>
                                <p><strong>Arrival:</strong> ${flightDetails.route_info.arrival.airport} (Terminal ${flightDetails.route_info.arrival.terminal})</p>
                                <p><strong>Check-in:</strong> ${flightDetails.route_info.departure.check_in_counter}</p>
                                <p><strong>Baggage Claim:</strong> ${flightDetails.route_info.arrival.baggage_claim}</p>
                            </div>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-md-6">
                                <h6><i class="fas fa-clock me-2"></i>Flight Schedule</h6>
                                <p><strong>Departure:</strong> ${flightDetails.flight_schedule.departure_time}</p>
                                <p><strong>Arrival:</strong> ${flightDetails.flight_schedule.arrival_time}</p>
                                <p><strong>Duration:</strong> ${flightDetails.flight_schedule.duration}</p>
                                <p><strong>Timezone:</strong> ${flightDetails.flight_schedule.timezone_info}</p>
                            </div>
                            <div class="col-md-6">
                                <h6><i class="fas fa-plane-departure me-2"></i>Aircraft Information</h6>
                                <p><strong>Type:</strong> ${flightDetails.aircraft_info.type}</p>
                                <p><strong>Registration:</strong> ${flightDetails.aircraft_info.registration}</p>
                                <p><strong>Capacity:</strong> ${flightDetails.aircraft_info.capacity}</p>
                                <p><strong>Configuration:</strong> ${flightDetails.aircraft_info.configuration}</p>
                            </div>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-md-6">
                                <h6><i class="fas fa-concierge-bell me-2"></i>Services</h6>
                                <p><strong>Entertainment:</strong> ${flightDetails.services.in_flight_entertainment}</p>
                                <p><strong>WiFi:</strong> ${flightDetails.services.wifi}</p>
                                <p><strong>Power Outlets:</strong> ${flightDetails.services.power_outlets}</p>
                                <p><strong>Meal Service:</strong> ${flightDetails.services.meal_service}</p>
                            </div>
                            <div class="col-md-6">
                                <h6><i class="fas fa-suitcase me-2"></i>Baggage Information</h6>
                                <p><strong>Checked:</strong> ${flightDetails.baggage_info.checked_baggage}</p>
                                <p><strong>Cabin:</strong> ${flightDetails.baggage_info.cabin_baggage}</p>
                                <p><strong>Excess:</strong> ${flightDetails.baggage_info.excess_baggage}</p>
                                <p><strong>Restricted:</strong> ${flightDetails.baggage_info.restricted_items}</p>
                            </div>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6><i class="fas fa-phone me-2"></i>Contact Information</h6>
                                <p><strong>Reservations:</strong> ${flightDetails.contact_info.reservations}</p>
                                <p><strong>Customer Service:</strong> ${flightDetails.contact_info.customer_service}</p>
                                <p><strong>Emergency:</strong> ${flightDetails.contact_info.emergency}</p>
                                <p><strong>Email:</strong> <a href="mailto:${flightDetails.contact_info.email}">${flightDetails.contact_info.email}</a></p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    async bookFlight(flightId) {
        // Show booking form
        this.showBookingForm(flightId);
    },

    showBookingForm(flightId) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Book Flight - ${flightId}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="bookingForm">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6>Passenger Details</h6>
                                    <div class="mb-3">
                                        <label class="form-label">Full Name</label>
                                        <input type="text" class="form-control" name="passenger_name" required>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Date of Birth</label>
                                        <input type="date" class="form-control" name="passenger_dob" required>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Passport Number</label>
                                        <input type="text" class="form-control" name="passport_number" required>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <h6>Contact Information</h6>
                                    <div class="mb-3">
                                        <label class="form-label">Email</label>
                                        <input type="email" class="form-control" name="contact_email" required>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Phone</label>
                                        <input type="tel" class="form-control" name="contact_phone" required>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Special Requests</label>
                                        <textarea class="form-control" name="special_requests" rows="3"></textarea>
                                    </div>
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" onclick="this.submitBooking('${flightId}')">Confirm Booking</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    async submitBooking(flightId) {
        try {
            const form = document.getElementById('bookingForm');
            const formData = new FormData(form);
            
            const passengerDetails = [{
                name: formData.get('passenger_name'),
                date_of_birth: formData.get('passenger_dob'),
                passport_number: formData.get('passport_number')
            }];
            
            const contactInfo = {
                email: formData.get('contact_email'),
                phone: formData.get('contact_phone'),
                special_requests: formData.get('special_requests')
            };
            
            const response = await fetch(`${this.apiBase}/flights/book/${flightId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    passenger_details: passengerDetails,
                    contact_info: contactInfo
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showBookingConfirmation(data.booking);
            } else {
                this.showNotification('Failed to book flight.', 'error');
            }
        } catch (error) {
            console.error('Error booking flight:', error);
            this.showNotification('An error occurred while booking the flight.', 'error');
        }
    },

    showBookingConfirmation(booking) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-success text-white">
                        <h5 class="modal-title"><i class="fas fa-check-circle me-2"></i>Booking Confirmed!</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-success">
                            <h6>Booking ID: ${booking.booking_id}</h6>
                            <p>Your flight has been successfully booked!</p>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Flight Details</h6>
                                <p><strong>Flight ID:</strong> ${booking.flight_id}</p>
                                <p><strong>Status:</strong> <span class="badge bg-success">${booking.status}</span></p>
                                <p><strong>Payment Status:</strong> <span class="badge bg-success">${booking.payment_status}</span></p>
                                <p><strong>Total Amount:</strong> $${booking.total_amount}</p>
                            </div>
                            <div class="col-md-6">
                                <h6>Travel Information</h6>
                                <p><strong>Check-in:</strong> ${booking.check_in_time}</p>
                                <p><strong>Baggage:</strong> ${booking.baggage_allowance}</p>
                                <p><strong>Boarding Pass:</strong> ${booking.boarding_pass}</p>
                                <p><strong>Contact:</strong> ${booking.contact_airline}</p>
                            </div>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Seat Assignments</h6>
                                ${booking.seat_assignments.map(seat => `
                                    <p><strong>${seat.passenger_name}:</strong> Seat ${seat.seat} (${seat.class})</p>
                                `).join('')}
                            </div>
                        </div>
                        
                        <div class="alert alert-info mt-3">
                            <h6>Important Information</h6>
                            <ul class="mb-0">
                                <li>Please arrive at the airport 2 hours before departure</li>
                                <li>Have your passport and travel documents ready</li>
                                <li>Check your email for detailed instructions</li>
                                <li>${booking.cancellation_policy}</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    async getCountryBudget(country, duration = 7, groupSize = 2, accommodationType = 'mid') {
        try {
            const response = await fetch(`${this.apiBase}/budget/country/${country}`);
            const data = await response.json();

            if (response.ok) {
                this.showCountryBudget(data, duration, groupSize, accommodationType);
            } else {
                this.showNotification('Failed to get budget information.', 'error');
            }
        } catch (error) {
            console.error('Error getting country budget:', error);
            this.showNotification('An error occurred while getting budget information.', 'error');
        }
    },

    showCountryBudget(budgetData, duration, groupSize, accommodationType) {
        const budget = budgetData.budgets[accommodationType];
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Budget Guide for ${budgetData.country}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <strong>Currency:</strong> ${budgetData.currency}<br>
                                <strong>Cost Level:</strong> ${budgetData.cost_level}<br>
                                <strong>Duration:</strong> ${duration} days<br>
                                <strong>Group Size:</strong> ${groupSize} people
                            </div>
                            <div class="col-md-6">
                                <strong>Accommodation Type:</strong> ${accommodationType}<br>
                                <strong>Total Budget:</strong> ${budgetData.currency} ${budget.total}<br>
                                <strong>Per Person:</strong> ${budgetData.currency} ${budget.per_person}
                            </div>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Budget Breakdown</h6>
                                <ul class="list-unstyled">
                                    <li><i class="fas fa-bed me-2"></i>Accommodation: ${budgetData.currency} ${budget.accommodation}</li>
                                    <li><i class="fas fa-utensils me-2"></i>Food: ${budgetData.currency} ${budget.food}</li>
                                    <li><i class="fas fa-car me-2"></i>Transport: ${budgetData.currency} ${budget.transport}</li>
                                    <li><i class="fas fa-hiking me-2"></i>Activities: ${budgetData.currency} ${budget.activities}</li>
                                    <li><i class="fas fa-plus me-2"></i>Additional: ${budgetData.currency} ${budget.additional}</li>
                                </ul>
                            </div>
                            <div class="col-md-6">
                                <h6>All Accommodation Types</h6>
                                <div class="mb-2">
                                    <strong>Budget:</strong> ${budgetData.currency} ${budgetData.budgets.budget.total}
                                </div>
                                <div class="mb-2">
                                    <strong>Mid-range:</strong> ${budgetData.currency} ${budgetData.budgets.mid.total}
                                </div>
                                <div class="mb-2">
                                    <strong>Luxury:</strong> ${budgetData.currency} ${budgetData.budgets.luxury.total}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        const bootstrapModal = new bootstrap.Modal(modal);
        bootstrapModal.show();
        
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    },

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(notification);

        // Auto remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }
};

// Global functions for modals
function showLoginModal() {
    const modal = new bootstrap.Modal(document.getElementById('loginModal'));
    modal.show();
}

function showRegisterModal() {
    const modal = new bootstrap.Modal(document.getElementById('registerModal'));
    modal.show();
}

function showMoodAnalyzer() {
    document.getElementById('mood-analyzer').scrollIntoView({ behavior: 'smooth' });
}

function showDestinations() {
    document.getElementById('destinations').scrollIntoView({ behavior: 'smooth' });
}

// Face Recognition Functions
let videoStream = null;

function startFaceRecognition() {
    const video = document.getElementById('video');
    const faceSection = document.getElementById('faceRecognitionSection');
    
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(function(stream) {
                videoStream = stream;
                video.srcObject = stream;
                faceSection.style.display = 'block';
                app.showNotification('Camera started! Click "Capture Photo" to analyze your mood.', 'success');
            })
            .catch(function(error) {
                console.error('Error accessing camera:', error);
                app.showNotification('Could not access camera. Please check permissions.', 'error');
            });
    } else {
        app.showNotification('Camera not supported in this browser.', 'error');
    }
}

function stopFaceRecognition() {
    const video = document.getElementById('video');
    const faceSection = document.getElementById('faceRecognitionSection');
    
    if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
        videoStream = null;
    }
    
    video.srcObject = null;
    faceSection.style.display = 'none';
    app.showNotification('Camera stopped.', 'info');
}

function capturePhoto() {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    
    if (!video || !video.videoWidth || !video.videoHeight) {
        app.showNotification('Camera not ready. Please wait for video to load.', 'warning');
        return;
    }
    
    const context = canvas.getContext('2d');
    
    // Set canvas size to match video (ensure minimum size for face detection)
    canvas.width = Math.max(video.videoWidth, 320);
    canvas.height = Math.max(video.videoHeight, 240);
    
    // Draw video frame to canvas with better quality
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    
    // Convert canvas to base64 image with good quality (0.9 for balance between size and quality)
    const imageData = canvas.toDataURL('image/jpeg', 0.9);
    
    // Show captured image briefly (optional)
    app.showNotification('Photo captured! Analyzing your mood...', 'info');
    
    // Analyze the captured image
    analyzeFaceMood(imageData);
}

async function analyzeFaceMood(imageData) {
    try {
        // Show loading state
        const resultDiv = document.getElementById('faceAnalysisResult');
        const contentDiv = document.getElementById('faceAnalysisContent');
        resultDiv.style.display = 'block';
        contentDiv.innerHTML = '<div class="text-center"><i class="fas fa-spinner fa-spin"></i> Analyzing your face...</div>';
        
        const response = await fetch('/api/mood/analyze-face', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                image: imageData, 
                prefer_cnn: true, 
                force_cycle: false, 
                force_variety: false  // Always use real predictions, never force variety
            })
        });

        const data = await response.json();

        if (response.ok && data.mood_analysis) {
            const analysis = data.mood_analysis;
            
            // Check if face was detected
            if (analysis.faces_detected === 0 || analysis.status === 'no_face') {
                contentDiv.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        <strong>No face detected!</strong><br>
                        Please ensure your face is clearly visible in the camera and try again.
                        <ul class="mt-2 mb-0">
                            <li>Make sure you're in good lighting</li>
                            <li>Look directly at the camera</li>
                            <li>Remove any obstructions</li>
                        </ul>
                    </div>
                `;
                app.showNotification('No face detected. Please try again with better lighting.', 'warning');
            } else {
                displayFaceAnalysisResult(analysis);
                app.showNotification(`Mood detected: ${analysis.mood}!`, 'success');
            }
        } else {
            app.showNotification(data.error || 'Face analysis failed', 'error');
            contentDiv.innerHTML = `<div class="alert alert-danger">${data.error || 'Analysis failed'}</div>`;
        }
    } catch (error) {
        console.error('Face analysis error:', error);
        app.showNotification('An error occurred during face analysis.', 'error');
        const contentDiv = document.getElementById('faceAnalysisContent');
        if (contentDiv) {
            contentDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
        }
    }
}

function displayFaceAnalysisResult(analysis) {
    const resultDiv = document.getElementById('faceAnalysisResult');
    const contentDiv = document.getElementById('faceAnalysisContent');
    
    const moodEmoji = {
        // Basic moods
        'happy': '😊', 'sad': '😢', 'angry': '😠', 'stressed': '😰',
        'relaxed': '😌', 'energetic': '⚡', 'adventurous': '🏔️',
        'romantic': '💕', 'neutral': '😐',
        
        // Positive moods (15+)
        'joyful': '😄', 'cheerful': '😃', 'excited': '🎉', 'ecstatic': '🤩',
        'blissful': '😇', 'euphoric': '🎊', 'radiant': '✨', 'vibrant': '🌈',
        'upbeat': '🎵', 'jubilant': '🎈', 'elated': '🎉', 'thrilled': '🎯',
        'delighted': '😍', 'pleased': '😊', 'satisfied': '😌',
        
        // Relaxed/Calm moods (12+)
        'calm': '🧘', 'content': '😊', 'peaceful': '🕊️', 'serene': '🌊',
        'tranquil': '🌿', 'zen': '🧘‍♂️', 'meditative': '🧘‍♀️', 'mellow': '🌅',
        'chill': '❄️', 'laidback': '🏖️', 'composed': '🎭', 'balanced': '⚖️',
        'centered': '🎯',
        
        // Energetic/Active moods (12+)
        'curious': '🤔', 'confident': '😎', 'bold': '💪', 'daring': '🎪',
        'dynamic': '⚡', 'vigorous': '🏃', 'lively': '💃', 'spirited': '🔥',
        'animated': '🎬', 'zealous': '⚡', 'enthusiastic': '🎉',
        
        // Emotional/Romantic moods (10+)
        'loving': '💖', 'passionate': '🔥', 'affectionate': '💝',
        'tender': '🌹', 'warm': '☀️', 'intimate': '💑', 'devoted': '💍',
        'adoring': '😍', 'enamored': '💘',
        
        // Negative/Stressed moods (12+)
        'anxious': '😟', 'worried': '😰', 'frustrated': '😤', 'overwhelmed': '😵',
        'tense': '😬', 'nervous': '😓', 'agitated': '😠', 'restless': '😣',
        'uneasy': '😕', 'troubled': '😞', 'distressed': '😟',
        
        // Mental/Thinking moods (10+)
        'focused': '🎯', 'concentrated': '🔍', 'determined': '💪',
        'ambitious': '🚀', 'motivated': '⚡', 'driven': '🏎️', 'analytical': '📊',
        'thoughtful': '🤔', 'contemplative': '🧘', 'reflective': '💭',
        
        // Creative/Artistic moods (8+)
        'creative': '🎨', 'artistic': '🖼️', 'imaginative': '🌈',
        'inspired': '💡', 'innovative': '🔬', 'expressive': '🎭',
        'visionary': '🔮', 'original': '✨',
        
        // Playful/Fun moods (8+)
        'playful': '😜', 'funny': '😂', 'humorous': '😆', 'silly': '🤪',
        'whimsical': '🎪', 'quirky': '🎨', 'lighthearted': '😄', 'carefree': '🦋',
        
        // Nostalgic/Dreamy moods (6+)
        'nostalgic': '📸', 'dreamy': '💭', 'sentimental': '💌',
        'wistful': '🌙', 'yearning': '💫', 'reminiscent': '📷',
        
        // Hopeful/Optimistic moods (6+)
        'hopeful': '🌟', 'optimistic': '☀️', 'positive': '➕',
        'encouraged': '👍', 'inspired': '💡',
        
        // Tired/Sleepy moods (4+)
        'tired': '😴', 'sleepy': '😪', 'exhausted': '😫', 'weary': '😩',
        
        // Neutral/Bored moods (6+)
        'bored': '😑', 'indifferent': '😐', 'apathetic': '😶',
        'uninterested': '😒', 'detached': '🧘', 'reserved': '🤐',
        
        // Mysterious/Serious moods (5+)
        'mysterious': '🕵️', 'serious': '😐', 'solemn': '🙏',
        'grave': '⚫', 'intense': '🔥',
        
        // Grateful/Proud moods (4+)
        'grateful': '🙏', 'proud': '🦁', 'thankful': '🙌', 'appreciative': '💝',
        
        // Melancholic/Sad moods (5+)
        'melancholic': '😔', 'sorrowful': '😢', 'gloomy': '☁️',
        'downcast': '😞',
        
        // Stoic/Skeptical moods (new)
        'thoughtful': '🤔', 'stoic': '🗿', 'resilient': '🛡️', 'recovering': '🌱',
        'skeptical': '🧐', 'inquisitive': '🔍', 'hopeful': '🌟', 'intrigued': '🤨',
        
        // Amazed/Surprised moods (4+)
        'amazed': '😲', 'astonished': '🤯', 'awestruck': '😱',
        'wonderstruck': '✨'
    };
    
    const moodLabels = {
        // Basic moods
        'happy': 'Happy', 'sad': 'Sad', 'angry': 'Angry', 'stressed': 'Stressed',
        'relaxed': 'Relaxed', 'energetic': 'Energetic', 'adventurous': 'Adventurous',
        'romantic': 'Romantic', 'neutral': 'Neutral',
        
        // Positive moods
        'joyful': 'Joyful', 'cheerful': 'Cheerful', 'excited': 'Excited',
        'ecstatic': 'Ecstatic', 'blissful': 'Blissful', 'euphoric': 'Euphoric',
        'radiant': 'Radiant', 'vibrant': 'Vibrant', 'upbeat': 'Upbeat',
        'jubilant': 'Jubilant', 'elated': 'Elated', 'thrilled': 'Thrilled',
        'delighted': 'Delighted', 'pleased': 'Pleased', 'satisfied': 'Satisfied',
        
        // Relaxed/Calm moods
        'calm': 'Calm', 'content': 'Content', 'peaceful': 'Peaceful',
        'serene': 'Serene', 'tranquil': 'Tranquil', 'zen': 'Zen',
        'meditative': 'Meditative', 'mellow': 'Mellow', 'chill': 'Chill',
        'laidback': 'Laidback', 'composed': 'Composed', 'balanced': 'Balanced',
        'centered': 'Centered',
        
        // Energetic/Active moods
        'curious': 'Curious', 'confident': 'Confident', 'bold': 'Bold',
        'daring': 'Daring', 'dynamic': 'Dynamic', 'vigorous': 'Vigorous',
        'lively': 'Lively', 'spirited': 'Spirited', 'animated': 'Animated',
        'zealous': 'Zealous', 'enthusiastic': 'Enthusiastic',
        
        // Emotional/Romantic moods
        'loving': 'Loving', 'passionate': 'Passionate', 'affectionate': 'Affectionate',
        'tender': 'Tender', 'warm': 'Warm', 'intimate': 'Intimate',
        'devoted': 'Devoted', 'adoring': 'Adoring', 'enamored': 'Enamored',
        
        // Negative/Stressed moods
        'anxious': 'Anxious', 'worried': 'Worried', 'frustrated': 'Frustrated',
        'overwhelmed': 'Overwhelmed', 'tense': 'Tense', 'nervous': 'Nervous',
        'agitated': 'Agitated', 'restless': 'Restless', 'uneasy': 'Uneasy',
        'troubled': 'Troubled', 'distressed': 'Distressed',
        
        // Mental/Thinking moods
        'focused': 'Focused', 'concentrated': 'Concentrated', 'determined': 'Determined',
        'ambitious': 'Ambitious', 'motivated': 'Motivated', 'driven': 'Driven',
        'analytical': 'Analytical', 'thoughtful': 'Thoughtful',
        'contemplative': 'Contemplative', 'reflective': 'Reflective',
        
        // Creative/Artistic moods
        'creative': 'Creative', 'artistic': 'Artistic', 'imaginative': 'Imaginative',
        'inspired': 'Inspired', 'innovative': 'Innovative', 'expressive': 'Expressive',
        'visionary': 'Visionary', 'original': 'Original',
        
        // Playful/Fun moods
        'playful': 'Playful', 'funny': 'Funny', 'humorous': 'Humorous',
        'silly': 'Silly', 'whimsical': 'Whimsical', 'quirky': 'Quirky',
        'lighthearted': 'Lighthearted', 'carefree': 'Carefree',
        
        // Nostalgic/Dreamy moods
        'nostalgic': 'Nostalgic', 'dreamy': 'Dreamy', 'sentimental': 'Sentimental',
        'wistful': 'Wistful', 'yearning': 'Yearning', 'reminiscent': 'Reminiscent',
        
        // Hopeful/Optimistic moods
        'hopeful': 'Hopeful', 'optimistic': 'Optimistic', 'positive': 'Positive',
        'encouraged': 'Encouraged',
        
        // Tired/Sleepy moods
        'tired': 'Tired', 'sleepy': 'Sleepy', 'exhausted': 'Exhausted',
        'weary': 'Weary',
        
        // Neutral/Bored moods
        'bored': 'Bored', 'indifferent': 'Indifferent', 'apathetic': 'Apathetic',
        'uninterested': 'Uninterested', 'detached': 'Detached', 'reserved': 'Reserved',
        
        // Mysterious/Serious moods
        'mysterious': 'Mysterious', 'serious': 'Serious', 'solemn': 'Solemn',
        'grave': 'Grave', 'intense': 'Intense',
        
        // Grateful/Proud moods
        'grateful': 'Grateful', 'proud': 'Proud', 'thankful': 'Thankful',
        'appreciative': 'Appreciative',
        
        // Melancholic/Sad moods
        'melancholic': 'Melancholic', 'sorrowful': 'Sorrowful', 'gloomy': 'Gloomy',
        'downcast': 'Downcast',
        
        // Stoic/Skeptical moods
        'thoughtful': 'Thoughtful', 'stoic': 'Stoic', 'resilient': 'Resilient',
        'recovering': 'Recovering', 'skeptical': 'Skeptical', 'inquisitive': 'Inquisitive',
        'hopeful': 'Hopeful', 'intrigued': 'Intrigued',
        
        // Amazed/Surprised moods
        'amazed': 'Amazed', 'astonished': 'Astonished', 'awestruck': 'Awestruck',
        'wonderstruck': 'Wonderstruck'
    };
    
    const methodLabels = {
        'cnn_trained': 'CNN Model',
        'deepface_emotion': 'DeepFace',
        'fer': 'FER',
        'cv_fallback': 'OpenCV',
        'cycle': 'Mood Variety',
        'cycle_variety': 'Mood Variety'
    };
    
    const confidencePercent = Math.round((analysis.confidence || 0) * 100);
    const emotionLabel = analysis.emotion_label || analysis.mood;
    
    contentDiv.innerHTML = `
        <div class="row">
            <div class="col-12">
                <div class="d-flex align-items-center mb-3">
                    <span style="font-size: 3rem;">${moodEmoji[analysis.mood] || '😐'}</span>
                    <div class="ms-3">
                        <h5 class="mb-1">Detected Mood: <strong>${moodLabels[analysis.mood] || analysis.mood}</strong></h5>
                        <p class="mb-0 text-muted">
                            <small>Emotion: ${emotionLabel} | Method: ${methodLabels[analysis.method] || analysis.method || 'CNN'}</small>
                        </p>
            </div>
        </div>
                <div class="progress mb-2" style="height: 25px;">
                    <div class="progress-bar ${confidencePercent > 70 ? 'bg-success' : confidencePercent > 50 ? 'bg-warning' : 'bg-info'}" 
                         role="progressbar" 
                         style="width: ${confidencePercent}%"
                         aria-valuenow="${confidencePercent}" 
                         aria-valuemin="0" 
                         aria-valuemax="100">
                        ${confidencePercent}% Confidence
                    </div>
                </div>
                ${analysis.faces_detected ? `<p class="mb-2"><small><i class="fas fa-check-circle text-success me-1"></i>Face detected successfully</small></p>` : ''}
                ${analysis.message ? `<p class="mb-0"><small class="text-info">${analysis.message}</small></p>` : ''}
            </div>
        </div>
        <div class="mt-3 d-grid gap-2">
            <button class="btn btn-primary" onclick="getRecommendationsFromMood('${analysis.mood}')">
                <i class="fas fa-map-marked-alt me-2"></i>Get Travel Recommendations for ${moodLabels[analysis.mood] || analysis.mood}
            </button>
            <button class="btn btn-outline-secondary btn-sm" onclick="capturePhoto()">
                <i class="fas fa-redo me-2"></i>Capture Again
            </button>
        </div>
    `;
    
    resultDiv.style.display = 'block';
}

function getRecommendationsFromMood(mood) {
    // Use the existing recommendation system with the detected mood
    app.getRecommendations(mood);
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    app.init();
}); 
 