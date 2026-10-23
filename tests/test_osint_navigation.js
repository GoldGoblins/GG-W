'use strict';
const assert = require('node:assert/strict');
const nav = require('../qml/osint-map/navigation.js');
let now = 1000000;
const fix = (lat = 59, lon = 18, accuracy = 8, timestamp = now) => ({timestamp,
    coords: {latitude: lat, longitude: lon, accuracy, heading: null, speed: null}});
assert.equal(nav.normalizeFix(fix(), now).heading, null);
assert.equal(nav.normalizeFix(fix(91), now), null);
assert.equal(nav.normalizeFix(fix(59, 18, -1), now), null);
assert.equal(nav.normalizeFix(fix(59, 18, 8, now - 121000), now), null);
assert.equal(nav.normalizeFix(fix(59, 18, 8, now + 11000), now), null);
assert.ok(Math.abs(nav.distance([0, 0], [0, 1]) - 111195) < 2);
assert.ok(nav.distance([179, 0], [-179, 0]) < 223000);
assert.ok(Math.abs(nav.bearing([0, 0], [1, 0]) - 90) < 0.001);

const route = nav.prepareRoute({ok: true, geometry: {type: 'LineString', coordinates: [[18, 59], [18.01, 59], [18.02, 59]]},
    distance_m: 1200, duration_s: 120, steps: [{at_m: 600, type: 'turn', modifier: 'right', name: 'Testvägen'}, {at_m: 1200, type: 'arrive'}]});
const middle = nav.progress(nav.normalizeFix(fix(59, 18.005), now), route);
assert.ok(Math.abs(middle.remaining_m - 900) < 1);
assert.ok(Math.abs(middle.eta_s - 90) < 1);
assert.equal(middle.next_step.name, 'Testvägen');
assert.equal(middle.off_route, false);
assert.equal(nav.progress(nav.normalizeFix(fix(59.01, 18.005), now), route).off_route, true);
assert.equal(nav.progress(nav.normalizeFix(fix(59, 18.005, 500), now), route).next_step, null);
assert.equal(nav.progress(nav.normalizeFix(fix(59, 18.02), now), route).arrived, true);
assert.equal(nav.prepareRoute({ok: true, geometry: {coordinates: [[18, 91], [18, 59]]}}), null);

let state = {hidden: false, ready: true, detailed: false};
let watches = [], clears = [], paints = [];
const tracker = nav.createPositionTracker({context: () => state, clock: () => now,
    geolocation: {watchPosition(success, error, options) { const id = watches.length; watches.push({success, error, options}); return id; }, clearWatch(id) { clears.push(id); }},
    onFix: value => paints.push(value)});
tracker.update();
assert.equal(watches.length, 0, 'startup must not obtain location');
tracker.setEnabled(true);
assert.equal(watches[0].options.enableHighAccuracy, false);
assert.equal(watches[0].options.maximumAge, 60000);
watches[0].success(fix());
assert.equal(paints.length, 1);
for (let i = 0; i < 100; i++) { now += 10; watches[0].success(fix()); }
assert.equal(paints.length, 1, 'overview marker updates are throttled');
state.detailed = true; tracker.update();
assert.deepEqual(clears, [0], 'switching accuracy must dispose the previous watcher');
assert.equal(watches[1].options.enableHighAccuracy, true);
now += 1000; watches[1].success(fix(59, 18.001));
assert.equal(paints.length, 2);
state.hidden = true; tracker.update();
assert.deepEqual(clears, [0, 1]);
assert.equal(tracker.getState().fresh, false);
watches[1].success(fix(60, 19));
assert.equal(tracker.getState().fix.lat, 59, 'late callbacks after pause must be ignored');
state.hidden = false; tracker.update();
assert.equal(watches.length, 3);
watches[2].error({code: 1});
assert.equal(tracker.getState().enabled, false);
assert.equal(tracker.getState().status, 'POSITION PERMISSION DENIED');
tracker.update(); assert.equal(watches.length, 3, 'denied position must not auto-restart');
tracker.restoreFix({lat: 58, lon: 17, accuracy_m: 10, timestamp: now - 600000, heading: null, speed_mps: null});
assert.equal(tracker.getState().fix.lat, 58);
assert.equal(tracker.getState().fresh, false, 'remembered positions must not become live fixes');
console.log('OSINT_NAVIGATION_TEST=PASS');
