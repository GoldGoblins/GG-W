/* Deterministic MapLibre bridge regression: no browser or network required. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
const element = id => {
    if (!elements.has(id)) elements.set(id, {hidden: false, style: {}, setAttribute() {}, appendChild() {}, addEventListener() {}});
    return elements.get(id);
};
const frames = [];
let instance;
class FakeMap {
    constructor(options) {
        instance = this;
        this.style = options.style;
        this.zoom = options.zoom;
        this.center = {lng: options.center[0], lat: options.center[1]};
        this.pitch = options.pitch;
        this.sources = new Map();
        this.events = new Map();
        this.onceEvents = new Map();
        this.terrain = null;
        this.uploads = 0;
        for (const [id, source] of Object.entries(this.style.sources)) this.addSource(id, source);
    }
    addSource(id, source) { this.style.sources[id] = source; this.sources.set(id, {setData: data => { this.uploads++; this.style.sources[id].data = data; }}); }
    getSource(id) { return this.sources.get(id); }
    getLayer(id) { return this.style.layers.find(layer => layer.id === id); }
    addLayer(layer, before) { const index = this.style.layers.findIndex(row => row.id === before); if (index < 0) this.style.layers.push(layer); else this.style.layers.splice(index, 0, layer); }
    moveLayer(id) { const layer = this.getLayer(id); this.style.layers = this.style.layers.filter(row => row.id !== id); this.style.layers.push(layer); }
    getStyle() { return this.style; }
    getZoom() { return this.zoom; }
    getCenter() { return this.center; }
    getBearing() { return 0; }
    getPitch() { return this.pitch; }
    getBounds() { return {toArray: () => [[-180, -90], [180, 90]]}; }
    setSourceTileLodParams(levels, ratio, id) { assert.equal(levels, 12); assert.equal(ratio, 1.25); assert.ok(this.getSource(id)); this.lodRequests = (this.lodRequests || 0) + 1; }
    getTerrain() { return this.terrain; }
    setTerrain(terrain) { this.terrain = terrain; }
    setLayoutProperty(id, key, value) { const layer = this.getLayer(id); layer.layout = {...layer.layout, [key]: value}; }
    setProjection() {}
    setSky() {}
    addControl() {}
    on(name, layer, callback) { if (typeof layer === 'function') this.events.set(name, layer); }
    once(name, callback) { this.onceEvents.set(name, callback); }
    emit(name, value) { const once = this.onceEvents.get(name); this.onceEvents.delete(name); if (once) once(value); const event = this.events.get(name); if (event) event(value); }
    setStyle(style, options) { this.styleOptions = options; this.style = options.transformStyle(this.style, style); for (const [id, source] of Object.entries(this.style.sources)) if (!this.sources.has(id)) this.addSource(id, source); this.emit('style.load'); }
    jumpTo(view) { this.center = {lng: view.center[0], lat: view.center[1]}; this.zoom = view.zoom; this.pitch = view.pitch; this.emit('moveend'); }
    flyTo(view) { this.easeTo(view); }
    easeTo(view) { this.cameraCalls = (this.cameraCalls || 0) + 1; if (view.pitch !== undefined) this.pitch = view.pitch; if (view.zoom !== undefined) this.zoom = view.zoom; if (view.center) this.center = {lng: view.center[0], lat: view.center[1]}; }
    getCanvas() { return {style: {}}; }
}
const watches = [], cleared = [];
const geolocation = {watchPosition(success, error, options) { watches.push({success, error, options}); return watches.length - 1; }, clearWatch(id) { cleared.push(id); }};
const window = {addEventListener() {}};
const context = {
    GgOsintNav: require('../qml/osint-map/navigation.js'),
    window, document: {hidden: false, addEventListener() {}, getElementById: element, createElement: () => element('node'), createTextNode: text => text},
    maplibregl: {Map: FakeMap, NavigationControl: class {}},
    fetch: async () => ({ok: true, json: async () => ({version: 8, sources: {openmaptiles: {type: 'vector'}}, layers: [{id: 'buildings-flat', type: 'fill', source: 'openmaptiles', 'source-layer': 'building'}]})}),
    ResizeObserver: class {observe() {}}, requestAnimationFrame: callback => { frames.push(callback); return frames.length; }, cancelAnimationFrame() {},
    console, Uint8Array, URL, navigator: {geolocation},
};
const flush = () => { while (frames.length) frames.shift()(); };
(async () => {
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../qml/osint-map/map.js'), 'utf8'), context);
    instance.emit('load');
    assert.equal(window.osintMapReady, true);
    assert.equal(instance.getSource('gg-terrain'), undefined, 'world startup must not request DEM');
    const point = {id: 'a', kind: 'aircraft', lat: 59, lon: 18, heading: 90};
    const uploads = instance.uploads;
    for (let i = 0; i < 100; i++) window.setOsintPoints([{...point, id: String(i)}]);
    assert.equal(frames.length, 1, 'bridge burst must coalesce into one frame');
    flush();
    assert.equal(instance.style.sources.events.data.features[0].properties.id, '99');
    assert.equal(instance.uploads - uploads, 1, 'unchanged empty collections must not upload');
    const commits = window.osintPerformance.pointCommits;
    const unchangedUploads = instance.uploads;
    for (let i = 0; i < 100; i++) { window.setOsintPoints([{...point, id: '99'}]); flush(); }
    assert.equal(instance.uploads, unchangedUploads);
    assert.equal(window.osintPerformance.pointCommits, commits);
    window.setOsintTerrain(true);
    assert.equal(instance.getSource('gg-terrain'), undefined, 'enabled terrain still waits for zoom');
    instance.zoom = 8;
    instance.emit('moveend'); flush();
    assert.equal(instance.getTerrain().source, 'gg-terrain');
    assert.equal(instance.style.sources['gg-terrain'].encoding, 'terrarium');
    assert.equal(instance.style.sources['gg-terrain'].maxzoom, 12);
    for (let i = 0; i < 8; i++) await Promise.resolve();
    assert.equal(instance.styleOptions.diff, true);
    assert.ok(instance.getSource('events'));
    assert.equal(instance.style.sources.events.data.features[0].properties.id, '99', 'style transition must preserve observations');
    assert.equal(instance.getTerrain().source, 'gg-terrain');
    window.setOsintBuildings(true);
    assert.equal(instance.getLayer('gg-buildings').minzoom, 14);
    window.setOsintBuildings(false);
    assert.equal(instance.getLayer('gg-buildings').layout.visibility, 'none');
    instance.emit('error', {sourceId: 'gg-terrain', error: new Error('tile unavailable')});
    assert.equal(instance.getTerrain(), null);
    assert.equal(window.osintMapReady, true, 'DEM failure must not disable the map');
    assert.equal(window.osintTerrainStatus, 'TERRAIN UNAVAILABLE');
    window.setOsintTerrain(true);
    assert.equal(instance.getTerrain().source, 'gg-terrain', 'toggle retries terrain');
    assert.equal(instance.lodRequests, 1, 'LOD configuration must not repeat on every move');
    instance.zoom = 5.75; instance.emit('zoom');
    assert.ok(instance.getTerrain(), 'terrain stays enabled within hysteresis band');
    instance.zoom = 5.4; instance.emit('zoom');
    assert.equal(instance.getTerrain(), null, 'zoom-out releases terrain before moveend');
    instance.zoom = 5.75; instance.emit('moveend'); flush();
    assert.equal(instance.getTerrain(), null, 'terrain waits for activation threshold');
    instance.zoom = 6; instance.emit('moveend'); flush();
    assert.ok(instance.getTerrain());
    const saved = window.getOsintView();
    window.restoreOsintView({...saved, terrainEnabled: false, buildingsEnabled: true});
    assert.equal(instance.getTerrain(), null);
    assert.equal(window.getOsintView().buildingsEnabled, true);
    assert.equal(watches.length, 0, 'map startup must not request location');
    window.setOsintPositionEnabled(true);
    assert.equal(watches[0].options.enableHighAccuracy, false);
    watches[0].success({timestamp: Date.now(), coords: {latitude: 59, longitude: 18, accuracy: 8, heading: null, speed: null}});
    assert.equal(window.getOsintPositionState().fresh, true);
    assert.equal(instance.style.sources['self-position'].data.features[0].geometry.coordinates[0], 18);
    assert.equal(instance.style.sources['self-position'].data.features.length, 2, 'precise position includes its accuracy circle');
    const ownUploads = instance.uploads;
    for (let i = 0; i < 100; i++) window.getOsintPositionState();
    assert.equal(instance.uploads, ownUploads, 'polling an unchanged own position must not reupload geometry');
    assert.equal(instance.style.layers[instance.style.layers.length - 1].id, 'self-position', 'own marker must render above waypoints');
    instance.zoom = 15.5; instance.emit('moveend'); flush();
    assert.equal(watches[1].options.enableHighAccuracy, true);
    assert.ok(cleared.includes(0));
    window.setOsintFollowing(true);
    instance.emit('dragstart');
    assert.equal(window.getOsintPositionState().following, false);
    assert.equal(window.getOsintPositionState().enabled, true, 'manual pan pauses camera following, not position');
    window.setOsintPositionEnabled(false);
    assert.equal(window.getOsintPositionState().fresh, false);
    assert.equal(instance.style.sources['self-position'].data.features[0].properties.fresh, 'no');
    window.restoreOsintPosition({lat: 59, lon: 18, accuracy_m: 100000, timestamp: Date.now()});
    assert.equal(instance.style.sources['self-position'].data.features.length, 1, 'coarse position must not show a falsely capped accuracy circle');
    console.log('OSINT_MAP_TEST=PASS (100 unchanged packets: 0 uploads; burst: 1 commit)');
})().catch(error => { console.error(error); process.exitCode = 1; });
