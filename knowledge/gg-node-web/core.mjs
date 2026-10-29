// Browser-only, bounded public-message verification. No wallet keys or mining.
export const LIMITS=Object.freeze({message:8192,items:64,storage:262144,dailyBytes:1048576});
const encoder=new TextEncoder();
const hex=b=>Array.from(new Uint8Array(b),v=>v.toString(16).padStart(2,'0')).join('');
const unhex=s=>{if(!/^[a-f0-9]{64}$/.test(s))throw Error('BAD_HASH');return Uint8Array.from(s.match(/../g),b=>parseInt(b,16));};
export const digest=async value=>hex(await crypto.subtle.digest('SHA-256',encoder.encode(JSON.stringify(value))));
export function base58(value) {
    const alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
    if(typeof value!=='string'||value.length>90||!value.length)throw Error('BAD_BASE58');
    let number=0n;
    for(const c of value){const d=alphabet.indexOf(c);if(d<0)throw Error('BAD_BASE58');number=number*58n+BigInt(d);}
    const bytes=[];while(number){bytes.unshift(Number(number&255n));number>>=8n;}
    for(const c of value){if(c!=='1')break;bytes.unshift(0);}
    return new Uint8Array(bytes);
}
export async function verifyWitness(root,proof,address) {
    if(!proof||!proof.leaf||!Array.isArray(proof.path)||proof.path.length!==2)return false;
    const leaf=proof.leaf;
    if(leaf.address!==address||typeof leaf.balance!=='string'||!/^\d{1,20}$/.test(leaf.balance)||!Number.isSafeInteger(leaf.nonce)||leaf.nonce<0)return false;
    let value=await digest(leaf);
    for(const p of proof.path){
        if(!['left','right'].includes(p.side))return false;
        const buffer=new Uint8Array(64),a=unhex(p.side==='left'?p.hash:value),b=unhex(p.side==='left'?value:p.hash);
        buffer.set(a);buffer.set(b,32);value=hex(await crypto.subtle.digest('SHA-256',buffer));
    }
    return value===root;
}
export async function verifyEnvelope(envelope,checkpoint) {
    const b=envelope?.body;
    if(!checkpoint||!/^gglab:[a-z0-9]{1,32}$/.test(checkpoint.chain_id)||!b||b.schema!=='gg.lab.tx.v1')throw Error('CHECKPOINT_REQUIRED');
    if(b.chain_id!==checkpoint.chain_id||b.account_root!==checkpoint.account_root)throw Error('WRONG_OR_STALE_CHECKPOINT');
    if(!Number.isSafeInteger(b.nonce)||b.nonce<0||typeof b.amount!=='string'||!/^\d{1,20}$/.test(b.amount)||BigInt(b.amount)<=0n||b.fee!=='1000'||b.sender===b.recipient)throw Error('BAD_AMOUNT_OR_NONCE');
    if(!await verifyWitness(b.account_root,envelope.sender_witness,b.sender)||!await verifyWitness(b.account_root,envelope.recipient_witness,b.recipient))throw Error('BAD_WITNESS');
    const leaf=envelope.sender_witness.leaf;
    if(leaf.nonce!==b.nonce||BigInt(leaf.balance)<BigInt(b.amount)+1000n)throw Error('INSUFFICIENT_OR_REPLAY');
    const publicKey=base58(b.sender),signature=base58(envelope.signature);
    if(publicKey.length!==32||signature.length!==64)throw Error('BAD_SIGNATURE_SIZE');
    const key=await crypto.subtle.importKey('raw',publicKey,{name:'Ed25519'},false,['verify']);
    if(!await crypto.subtle.verify('Ed25519',key,signature,encoder.encode(JSON.stringify(b))))throw Error('BAD_SIGNATURE');
    return {id:await digest(envelope),state:'WITNESS_AND_SIGNATURE_VERIFIED'};
}
export class PublicQueue {
    constructor(saved=[],now=Date.now){this.now=now;this.items=[];this.bytes=0;this.day='';this.spent=0;this.paused=true;for(const item of saved.slice(0,LIMITS.items)){if(typeof item.raw==='string'&&item.expires>now())this._restore(item);}}
    _restore(item){const size=encoder.encode(item.raw).length;if(size<=LIMITS.message&&this.bytes+size<=LIMITS.storage&&!this.items.some(x=>x.id===item.id)){this.items.push({...item,size});this.bytes+=size;}}
    prune(){this.items=this.items.filter(x=>x.expires>this.now());this.bytes=this.items.reduce((n,x)=>n+x.size,0);}
    async add(raw,checkpoint){
        this.prune();if(this.paused)throw Error('PAUSED');
        const size=encoder.encode(raw).length;if(size>LIMITS.message)throw Error('MESSAGE_TOO_LARGE');
        const today=new Date(this.now()).toISOString().slice(0,10);if(today!==this.day){this.day=today;this.spent=0;}
        if(this.items.length>=LIMITS.items||this.bytes+size>LIMITS.storage)throw Error('QUEUE_FULL');
        if(this.spent+size>LIMITS.dailyBytes)throw Error('DATA_BUDGET');
        // Charge invalid and duplicate attempts too; verification is not free.
        this.spent+=size;
        const envelope=JSON.parse(raw),result=await verifyEnvelope(envelope,checkpoint);
        if(this.items.some(x=>x.id===result.id))return {...result,state:'DUPLICATE'};
        this.items.push({id:result.id,raw,size,expires:this.now()+300000,state:result.state});this.bytes+=size;return result;
    }
}
