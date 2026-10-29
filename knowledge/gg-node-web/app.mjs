import {PublicQueue} from './core.mjs';
const $=id=>document.getElementById(id),queue=new PublicQueue();
let database=null,lowBattery=false,busy=false,wanted=false;
function log(message){$('events').textContent=(new Date().toLocaleTimeString()+'  '+message+'\n'+$('events').textContent).slice(0,6000);}
function paint(){
    queue.prune();queue.paused=!wanted||($('visibleOnly').checked&&document.hidden)||($('battery').checked&&lowBattery);
    $('status').textContent=busy?'Verifierar…':queue.paused?'Pausad':'Redo · lokalt';$('dot').classList.toggle('active',!queue.paused);
    $('toggle').textContent=wanted?'Pausa':'Starta lokal verifiering';$('toggle').setAttribute('aria-pressed',String(wanted));
    $('verify').disabled=queue.paused||busy;$('storage').textContent=`Kö ${queue.items.length}/64 · ${queue.bytes}/262144 byte · kontrollerad indata ${queue.spent}/1048576 byte`;
}
async function persist(){if(!database)return;return new Promise((resolve,reject)=>{const tx=database.transaction('queue','readwrite');tx.objectStore('queue').put(queue.items,'public');tx.oncomplete=resolve;tx.onerror=()=>reject(Error('STORAGE_FAILED'));});}
try {
    const request=indexedDB.open('gg-public-node-v1',1);request.onupgradeneeded=()=>request.result.createObjectStore('queue');
    request.onsuccess=()=>{database=request.result;const get=database.transaction('queue').objectStore('queue').get('public');get.onsuccess=()=>{const restored=new PublicQueue(get.result||[]);queue.items=restored.items;queue.bytes=restored.bytes;paint();};};
    request.onerror=()=>log('Lagring ej tillgänglig · kön finns endast i minnet');
} catch(e){log('Lagring ej tillgänglig');}
$('toggle').onclick=()=>{wanted=!wanted;paint();log(queue.paused?'PAUSED':'READY');};
$('visibleOnly').onchange=$('battery').onchange=paint;document.addEventListener('visibilitychange',paint);
$('clear').onclick=async()=>{queue.items=[];queue.bytes=0;await persist().catch(()=>log('STORAGE_FAILED'));paint();log('Kö tömd');};
$('verify').onclick=async()=>{
    if(busy)return;busy=true;paint();
    try {
        let raw=$('message').value;const input=JSON.parse(raw);
        // A desktop-exported bundle can fill the two public fields together.
        if(input.envelope&&input.checkpoint){raw=JSON.stringify(input.envelope);if(!$('checkpoint').value.trim())$('checkpoint').value=JSON.stringify(input.checkpoint);}
        const result=await queue.add(raw,JSON.parse($('checkpoint').value));await persist();log(result.state);
    }
    catch(e){log(e instanceof SyntaxError?'INVALID_JSON':String(e.message).slice(0,100));}
    finally{busy=false;paint();}
};
$('export').onclick=()=>{queue.prune();const url=URL.createObjectURL(new Blob([JSON.stringify(queue.items)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='gg-public-queue.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
if(navigator.getBattery)navigator.getBattery().then(b=>{const update=()=>{lowBattery=!b.charging&&b.level<.2;paint();};b.addEventListener('levelchange',update);b.addEventListener('chargingchange',update);update();}).catch(()=>log('Batteristatus saknas'));
if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').then(()=>log('Offlinepaket registrerat')).catch(()=>log('Offlinepaket ej tillgängligt'));
if(!crypto.subtle){wanted=false;log('HTTPS eller localhost krävs för verifiering');}
paint();
