/**
 * Map View — Location Deduction with Leaflet
 * Shows all UP districts and highlights the user's deduced district.
 */

(function () {
    let map = null;
    let districtsLayer = null;
    let userMarker = null;
    let districtHighlight = null;
    let isMapInitialized = false;

    // Expose globally
    window.openMapPanel = openMapPanel;
    window.closeMapPanel = closeMapPanel;

    // Marks `district` as the user's active location — same effect the
    // full-screen splash flow has on first load (see index.html's
    // locationSplashFlow), but reachable any time from here: either by
    // clicking a district dot below, or when this panel's own geolocation
    // call succeeds. This is what actually turns the top-bar "Location Off"
    // badge into a real district name.
    //
    // Also refreshes the big greeting headline (window._greetingData /
    // window.refreshGreeting from index.html) to match, so manually picking
    // a district here has the same effect as the automatic GPS-detected
    // flow — previously this only updated the top-bar badge, leaving the
    // greeting stuck on its static "The mic is yours" placeholder whenever
    // geolocation was off/denied and the user picked a district by hand
    // instead. Pass `stats` directly if the caller already has today/
    // yesterday/week/total counts (avoids a redundant fetch); otherwise
    // pass `lat`/`lng` and they'll be looked up via /api/location.
    async function setActiveLocation(district, { lat, lng, stats } = {}) {
        window._detectedDistrict = district;

        const badge = document.getElementById('locationBadge');
        const badgeText = document.getElementById('locationText');
        const badgePulse = document.getElementById('locationPulse');

        if (badgeText) badgeText.textContent = district;
        if (badge) badge.classList.add('detected');
        if (badgePulse) badgePulse.remove();

        let greetingStats = stats;
        if (!greetingStats && lat != null && lng != null) {
            try {
                const res = await fetch('/api/location', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ latitude: lat, longitude: lng })
                });
                const data = await res.json();
                greetingStats = {
                    districtName: data.district,
                    todayCount: data.today_count,
                    yesterdayCount: data.yesterday_count,
                    weekCount: data.week_count,
                    totalCount: data.total_count
                };
            } catch (e) {
                console.error('Failed to refresh greeting stats for', district, e);
            }
        }
        if (greetingStats) {
            window._greetingData = greetingStats;
            window._greetingIndex = 0;
            window.refreshGreeting?.();
        }
    }

    function openMapPanel() {
        const panel = document.getElementById('mapPanel');
        if (!panel) return;
        panel.classList.add('open');

        if (!isMapInitialized) {
            setTimeout(() => {
                initMap();
                isMapInitialized = true;
                loadDistrictsAndDetect();
            }, 350); // wait for panel slide animation
        } else {
            map.invalidateSize();
        }
    }

    function closeMapPanel() {
        const panel = document.getElementById('mapPanel');
        if (panel) panel.classList.remove('open');
    }

    function initMap() {
        const container = document.getElementById('mapContainer');
        if (!container) return;

        map = L.map('mapContainer', {
            center: [27.0, 80.5],
            zoom: 7,
            zoomControl: false,
            attributionControl: false
        });

        // CARTO's old anonymous rastertiles/voyager endpoint now returns
        // "API KEY REQUIRED" placeholder tiles (CARTO cut off unregistered
        // access) — switched to OpenStreetMap's standard tile server, which
        // stays free/keyless under OSM's usage policy.
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            subdomains: 'abc'
        }).addTo(map);

        // Custom zoom control position
        L.control.zoom({ position: 'bottomright' }).addTo(map);

        // Attribution
        L.control.attribution({ position: 'bottomleft', prefix: '' })
            .addAttribution('© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors')
            .addTo(map);
    }

    async function loadDistrictsAndDetect() {
        const infoCard = document.getElementById('districtInfoCard');
        const infoName = document.getElementById('districtInfoName');
        const infoStatus = document.getElementById('districtInfoStatus');

        // Show detecting state
        if (infoCard) infoCard.classList.add('visible');
        if (infoStatus) infoStatus.textContent = 'Detecting your location...';
        if (infoName) infoName.textContent = '—';

        try {
            // Load all districts
            const distRes = await fetch('/api/districts');
            const distData = await distRes.json();
            renderDistricts(distData.districts);

            // Detect user location
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    async (pos) => {
                        const lat = pos.coords.latitude;
                        const lng = pos.coords.longitude;

                        if (infoStatus) infoStatus.textContent = 'Deducing district...';

                        try {
                            const locRes = await fetch('/api/location', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ latitude: lat, longitude: lng })
                            });
                            const locData = await locRes.json();

                            // Add user position marker
                            addUserMarker(lat, lng);

                            // Highlight deduced district
                            highlightDistrict(locData.district, locData.lat, locData.lng);

                            // Update info card
                            if (infoName) infoName.textContent = locData.district;
                            if (infoStatus) infoStatus.textContent = 'District Deduced';

                            setActiveLocation(locData.district, { stats: {
                                districtName: locData.district,
                                todayCount: locData.today_count,
                                yesterdayCount: locData.yesterday_count,
                                weekCount: locData.week_count,
                                totalCount: locData.total_count
                            }});

                        } catch (err) {
                            console.error('Location API error:', err);
                            if (infoStatus) infoStatus.textContent = 'Error deducing district';
                        }
                    },
                    (err) => {
                        console.warn('Geolocation denied:', err);
                        if (infoStatus) infoStatus.textContent = 'Location access denied';
                        if (infoName) infoName.textContent = 'Grant permission to detect';
                    },
                    // Same tradeoff as the first-visit location splash
                    // (index.html): this only buckets into one of ~46 known
                    // UP districts, so the faster wifi/IP-based fix is plenty.
                    { enableHighAccuracy: false, timeout: 3000 }
                );
            } else {
                if (infoStatus) infoStatus.textContent = 'Geolocation not supported';
            }
        } catch (err) {
            console.error('Failed to load districts:', err);
            if (infoStatus) infoStatus.textContent = 'Failed to load map data';
        }
    }

    function renderDistricts(districts) {
        if (!map) return;

        districtsLayer = L.layerGroup().addTo(map);

        districts.forEach(d => {
            const marker = L.circleMarker([d.lat, d.lng], {
                radius: 6,
                fillColor: '#64748b',
                color: '#94a3b8',
                weight: 1,
                opacity: 0.9,
                fillOpacity: 0.7,
                className: 'district-dot'
            });

            const countLabel = d.today_count !== undefined ? ` (${d.today_count} today)` : ' (0 today)';
            marker.bindTooltip(`${d.name}${countLabel}`, {
                permanent: true,
                direction: 'top',
                offset: [0, -8],
                className: 'district-tooltip',
                interactive: true
            });

            marker.on('click', () => {
                highlightDistrict(d.name, d.lat, d.lng);
                const infoName = document.getElementById('districtInfoName');
                const infoStatus = document.getElementById('districtInfoStatus');
                const infoCard = document.getElementById('districtInfoCard');
                if (infoName) infoName.textContent = d.name;
                if (infoStatus) infoStatus.textContent = 'Selected District';
                if (infoCard) infoCard.classList.add('visible');

                // Picking a district by hand is a valid way to "give your
                // location" when geolocation is off/denied — same effect as
                // it being auto-detected. `d` only carries today_count (see
                // /api/districts), so fetch the rest via lat/lng.
                setActiveLocation(d.name, { lat: d.lat, lng: d.lng });

                // Load and open social media feed for this district
                const feedPanel = document.getElementById('feedPanel');
                if (feedPanel) {
                    feedPanel.classList.add('open');
                }
                if (window.loadFeed) {
                    window.loadFeed(d.name);
                }
            });

            districtsLayer.addLayer(marker);
        });
    }

    function addUserMarker(lat, lng) {
        if (!map) return;

        // Remove old user marker
        if (userMarker) {
            map.removeLayer(userMarker);
        }

        // Pulsing HTML marker for user's actual location
        const pulseIcon = L.divIcon({
            className: 'user-pulse-marker',
            html: `
                <div class="pulse-ring"></div>
                <div class="pulse-core"></div>
            `,
            iconSize: [20, 20],
            iconAnchor: [10, 10]
        });

        userMarker = L.marker([lat, lng], { icon: pulseIcon, zIndexOffset: 1000 }).addTo(map);
        userMarker.bindTooltip('Your Location', {
            permanent: false,
            direction: 'top',
            offset: [0, -14],
            className: 'district-tooltip user-tooltip'
        });
    }

    function highlightDistrict(name, lat, lng) {
        if (!map) return;

        // Remove old highlight
        if (districtHighlight) {
            map.removeLayer(districtHighlight);
        }

        // Glowing highlight marker
        const glowIcon = L.divIcon({
            className: 'district-glow-marker',
            html: `
                <div class="glow-ring"></div>
                <div class="glow-ring glow-ring-2"></div>
                <div class="glow-core"></div>
            `,
            iconSize: [40, 40],
            iconAnchor: [20, 20]
        });

        districtHighlight = L.marker([lat, lng], { icon: glowIcon, zIndexOffset: 900 }).addTo(map);
        districtHighlight.bindTooltip(`📍 ${name}`, {
            permanent: true,
            direction: 'top',
            offset: [0, -24],
            className: 'district-tooltip highlight-tooltip'
        });

        // Smooth fly to the district
        map.flyTo([lat, lng], 10, {
            duration: 1.5,
            easeLinearity: 0.25
        });
    }

})();
