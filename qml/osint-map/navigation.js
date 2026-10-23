/* Own-position and route math. No network requests or location persistence. */
'use strict';
(function(root) {
    const radians = Math.PI / 180;
    const earth = 6371000;
    const valid = pair => Array.isArray(pair) && Number.isFinite(pair[0]) && Number.isFinite(pair[1])
        && Math.abs(pair[0]) <= 180 && Math.abs(pair[1]) <= 90;
    const wrap = value => ((value + 540) % 360) - 180;
    function distance(a, b) {
        const p = (b[1] - a[1]) * radians, q = wrap(b[0] - a[0]) * radians;
        const h = Math.sin(p / 2) ** 2 + Math.cos(a[1] * radians) * Math.cos(b[1] * radians) * Math.sin(q / 2) ** 2;
        return earth * 2 * Math.atan2(Math.sqrt(Math.min(1, h)), Math.sqrt(Math.max(0, 1 - h)));
    }
    function bearing(a, b) {
        const q = wrap(b[0] - a[0]) * radians, p1 = a[1] * radians, p2 = b[1] * radians;
        return (Math.atan2(Math.sin(q) * Math.cos(p2), Math.cos(p1) * Math.sin(p2)
            - Math.sin(p1) * Math.cos(p2) * Math.cos(q)) / radians + 360) % 360;
    }
    function prepareRoute(payload) {
        const raw = payload && payload.ok && payload.geometry && payload.geometry.coordinates;
        if (!Array.isArray(raw) || raw.length < 2 || raw.some(pair => !valid(pair)))
            return null;
        // Bound work per fix; retain both endpoints on long driving routes.
        const stride = Math.max(1, Math.ceil(raw.length / 20000));
        const coordinates = raw.filter((_, index) => index % stride === 0 || index === raw.length - 1);
        const cumulative = [0];
        for (let i = 1; i < coordinates.length; i++)
            cumulative.push(cumulative[i - 1] + distance(coordinates[i - 1], coordinates[i]));
        const total = cumulative[cumulative.length - 1];
        if (total <= 0) return null;
        return {coordinates, cumulative, total,
            distance_m: Number(payload.distance_m) > 0 ? Number(payload.distance_m) : total,
            duration_s: Math.max(0, Number(payload.duration_s) || 0),
            steps: (Array.isArray(payload.steps) ? payload.steps : []).slice(0, 2048)};
    }
    function progress(fix, route) {
        if (!fix || !route) return null;
        const point = [fix.lon, fix.lat];
        const scale = Math.max(0.001, Math.cos(fix.lat * radians));
        let nearest = Infinity, along = 0, direction = null;
        for (let i = 1; i < route.coordinates.length; i++) {
            const a = route.coordinates[i - 1], b = route.coordinates[i];
            const ax = wrap(a[0] - point[0]) * radians * earth * scale, ay = (a[1] - point[1]) * radians * earth;
            const bx = wrap(b[0] - point[0]) * radians * earth * scale, by = (b[1] - point[1]) * radians * earth;
            const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy;
            const t = length > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length)) : 0;
            const cross = Math.hypot(ax + t * dx, ay + t * dy);
            if (cross < nearest) {
                nearest = cross;
                along = route.cumulative[i - 1] + t * (route.cumulative[i] - route.cumulative[i - 1]);
                direction = bearing(a, b);
            }
        }
        const traveled = Math.max(0, Math.min(route.distance_m, along / route.total * route.distance_m));
        const remaining = Math.max(0, route.distance_m - traveled);
        const approximate = fix.accuracy_m > 100;
        const offRoute = nearest > Math.max(50, fix.accuracy_m * 1.5);
        const next = route.steps.find(step => Number(step.at_m) > traveled + 12) || null;
        return {remaining_m: remaining, eta_s: route.duration_s * remaining / route.distance_m,
            traveled_m: traveled, cross_track_m: nearest, bearing: direction,
            approximate, off_route: offRoute, arrived: !approximate && !offRoute && remaining < 30,
            next_step: approximate || offRoute ? null : next,
            next_step_m: next ? Math.max(0, Number(next.at_m) - traveled) : null};
    }
    function normalizeFix(position, now = Date.now(), maxAge = 120000) {
        const c = position && position.coords, stamp = position && position.timestamp;
        if (!c || !valid([c.longitude, c.latitude]) || !Number.isFinite(c.accuracy) || c.accuracy < 0
            || !Number.isFinite(stamp) || stamp > now + 10000 || now - stamp > maxAge)
            return null;
        return {lat: c.latitude, lon: c.longitude, accuracy_m: c.accuracy, timestamp: stamp,
            heading: Number.isFinite(c.heading) && c.heading >= 0 && c.heading < 360 ? c.heading : null,
            speed_mps: Number.isFinite(c.speed) && c.speed >= 0 ? c.speed : null};
    }
    function createPositionTracker({geolocation, context, onFix, clock = Date.now}) {
        let enabled = false, watch = null, generation = 0, mode = '', fix = null, lastPaint = -Infinity;
        let status = 'POSITION OFF';
        const stop = () => {
            generation++;
            if (watch !== null && geolocation) geolocation.clearWatch(watch);
            watch = null; mode = '';
        };
        function update() {
            const view = context();
            if (!enabled || view.hidden || !view.ready) {
                stop();
                if (enabled) status = 'POSITION PAUSED';
                return;
            }
            if (!geolocation || typeof geolocation.watchPosition !== 'function') {
                enabled = false; stop(); status = 'POSITION UNAVAILABLE'; return;
            }
            const next = view.detailed ? 'navigation' : 'overview';
            if (watch !== null && next === mode) return;
            stop(); mode = next; status = fix ? 'POSITION ON' : 'LOCATING…';
            const token = generation;
            let denied = false;
            const id = geolocation.watchPosition(position => {
                if (token !== generation || !enabled) return;
                const value = normalizeFix(position, clock());
                if (!value || (fix && value.timestamp < fix.timestamp)) return;
                fix = value; status = 'POSITION ON';
                const interval = mode === 'navigation' ? 1000 : 15000;
                if (clock() - lastPaint >= interval) { lastPaint = clock(); onFix(value); }
            }, error => {
                if (token !== generation) return;
                status = error && error.code === 1 ? 'POSITION PERMISSION DENIED'
                    : error && error.code === 3 ? 'POSITION TIMEOUT' : 'POSITION UNAVAILABLE';
                if (error && error.code === 1) { denied = true; enabled = false; stop(); }
            }, {enableHighAccuracy: next === 'navigation', maximumAge: next === 'navigation' ? 1500 : 60000, timeout: 15000});
            if (denied) geolocation.clearWatch(id); else watch = id;
        }
        return {
            restoreFix(value) {
                const restored = value && normalizeFix({timestamp: value.timestamp,
                    coords: {latitude: value.lat, longitude: value.lon, accuracy: value.accuracy_m,
                        heading: value.heading, speed: value.speed_mps}}, clock(), Infinity);
                if (restored) { fix = restored; status = 'LAST POSITION'; }
                return restored;
            },
            setEnabled(value) { enabled = Boolean(value); if (!enabled) status = fix ? 'LAST POSITION' : 'POSITION OFF'; lastPaint = -Infinity; update(); },
            update,
            stop,
            getState() { return {enabled, mode, status, fix, fresh: Boolean(enabled && watch !== null && fix && clock() - fix.timestamp < 90000)}; }
        };
    }
    const api = {distance, bearing, prepareRoute, progress, normalizeFix, createPositionTracker};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.GgOsintNav = api;
})(globalThis);
