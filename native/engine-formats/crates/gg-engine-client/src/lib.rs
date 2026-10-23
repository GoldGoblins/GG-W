//! Supervised C ABI client over upstream SRP and complete packet APIs.
//! No credentials, session keys or packet bodies are logged or saved.
#![recursion_limit="512"]
use std::{io::{Read,Write},net::{TcpStream,ToSocketAddrs,Shutdown},time::{Duration,Instant},slice,panic::{catch_unwind,AssertUnwindSafe}};
use serde_json::{Value,json};
pub use engine_protocol::{messages,wire};
use engine_protocol::{messages::{opcode,ServerPacket},auth};
use engine_srp::{NormalizedString,vanilla_header::{EncrypterHalf,DecrypterHalf,ProofSeed}};
mod values;
mod ping;
use values::{ToJson,FromJson};
// Movement helper is an unchanged source inclusion from the original protocol.
#[allow(dead_code)] #[path="../../engine-protocol/src/world/movement.rs"] mod movement;
#[allow(unused_imports)] mod verbs{use super::*;include!(concat!(env!("OUT_DIR"),"/verbs.rs"));}
const MAX_MESSAGE:usize=8*1024*1024;
struct Writer{stream:Option<TcpStream>,encrypter:Option<EncrypterHalf>,chat_language:u32,preview:Vec<Value>}
impl Writer{
    fn send(&mut self,opcode:u16,body:&[u8])->anyhow::Result<()>{
        if body.len()>65531{anyhow::bail!("world packet capacity exceeded");}
        let size=(body.len()+4) as u16;let s=size.to_be_bytes();let o=u32::from(opcode).to_le_bytes();let mut header=[s[0],s[1],o[0],o[1],o[2],o[3]];
        if let Some(crypto)=self.encrypter.as_mut(){crypto.encrypt(&mut header);}
        if let Some(stream)=self.stream.as_mut(){
            let mut packet=Vec::with_capacity(6+body.len());packet.extend(header);packet.extend(body);let end=Instant::now()+Duration::from_secs(5);let mut at=0;
            while at<packet.len(){match stream.write(&packet[at..]){Ok(0)=>anyhow::bail!("world connection closed"),Ok(n)=>at+=n,Err(e) if e.kind()==std::io::ErrorKind::WouldBlock&&Instant::now()<end=>std::thread::sleep(Duration::from_millis(1)),Err(_)=>anyhow::bail!("world send failed")}}
        }else{self.preview.push(json!({"opcode":opcode,"body":body}));}
        Ok(())
    }
}
struct Wire{stream:TcpStream,decrypter:DecrypterHalf,buffer:Vec<u8>,body:Option<(u16,usize)>}
impl Wire{
    fn packet(&mut self)->Result<Option<(u16,Vec<u8>)>,String>{
        if self.body.is_none()&&self.buffer.len()>=4{
            let mut header:[u8;4]=self.buffer[..4].try_into().unwrap();self.decrypter.decrypt(&mut header);self.buffer.drain(..4);
            let size=u16::from_be_bytes([header[0],header[1]]);if size<2{return Err("invalid world packet header".into());}
            self.body=Some((u16::from_le_bytes([header[2],header[3]]),(size-2) as usize));
        }
        if let Some((op,n))=self.body{if self.buffer.len()>=n{self.body=None;return Ok(Some((op,self.buffer.drain(..n).collect())));}}
        let mut data=[0u8;65536];
        match self.stream.read(&mut data){Ok(0)=>Err("world connection closed".into()),Ok(n)=>{if self.buffer.len()+n>128*1024{return Err("world receive capacity exceeded".into());}self.buffer.extend_from_slice(&data[..n]);self.packet_buffer()},Err(e) if e.kind()==std::io::ErrorKind::WouldBlock=>Ok(None),Err(_)=>Err("world receive failed".into())}
    }
    fn packet_buffer(&mut self)->Result<Option<(u16,Vec<u8>)>,String>{
        if self.body.is_none()&&self.buffer.len()>=4{
            let mut h:[u8;4]=self.buffer[..4].try_into().unwrap();self.decrypter.decrypt(&mut h);self.buffer.drain(..4);let size=u16::from_be_bytes([h[0],h[1]]);
            if size<2{return Err("invalid world packet header".into());}self.body=Some((u16::from_le_bytes([h[2],h[3]]),(size-2) as usize));
        }
        if let Some((op,n))=self.body{if self.buffer.len()>=n{self.body=None;return Ok(Some((op,self.buffer.drain(..n).collect())));}}
        Ok(None)
    }
}
struct Client{response:Vec<u8>,logon:Option<engine_protocol::Logon>,username:String,writer:Option<Writer>,wire:Option<Wire>,phase:&'static str,realm:Option<usize>,characters:Vec<messages::Character>,self_guid:Option<u64>,last_ping:Instant,clock:ping::Clock,queue:Option<u32>}
impl Client{
    fn new()->Self{Self{response:Vec::new(),logon:None,username:String::new(),writer:None,wire:None,phase:"LOGIN",realm:None,characters:Vec::new(),self_guid:None,last_ping:Instant::now(),clock:ping::Clock::default(),queue:None}}
    fn reset_world(&mut self){if let Some(w)=self.wire.take(){let _=w.stream.shutdown(Shutdown::Both);}self.writer=None;self.realm=None;self.characters.clear();self.self_guid=None;self.queue=None;self.phase=if self.logon.is_some(){"REALMS"}else{"LOGIN"};}
    fn state(&self)->Value{json!({"phase":self.phase,"realms":self.logon.as_ref().map(|l|l.realms.to_json()).unwrap_or(json!([])),"realm_index":self.realm,"characters":self.characters.to_json(),"self_guid":self.self_guid.to_json(),"queue":self.queue,"latency_ms":self.clock.average().unwrap_or(0)})}
    fn realm_connect(&mut self,index:usize)->Result<(),String>{
        let l=self.logon.as_ref().ok_or("login required")?;let realm=l.realms.get(index).ok_or("invalid realm selection")?;
        if realm.flags&3!=0{return Err("selected realm is unavailable".into());}
        let address=realm.address.clone();let key=l.session_key;
        self.reset_world();let mut stream=None;
        for addr in address.to_socket_addrs().map_err(|_|"realm address lookup failed")?.take(8){if let Ok(s)=TcpStream::connect_timeout(&addr,Duration::from_secs(5)){stream=Some(s);break;}}
        let mut stream=stream.ok_or("realm connection failed")?;stream.set_read_timeout(Some(Duration::from_secs(10))).map_err(|_|"realm socket failed")?;stream.set_nodelay(true).map_err(|_|"realm socket failed")?;
        let mut header=[0u8;4];stream.read_exact(&mut header).map_err(|_|"realm challenge failed")?;let size=u16::from_be_bytes([header[0],header[1]]);
        if size<2{return Err("invalid realm challenge".into());}let mut body=vec![0;(size-2) as usize];stream.read_exact(&mut body).map_err(|_|"realm challenge failed")?;
        let seed=match messages::parse_server(u16::from_le_bytes([header[2],header[3]]),&body).map_err(|_|"invalid realm challenge")?{ServerPacket::AuthChallenge{server_seed}=>server_seed,_=>return Err("invalid realm challenge".into())};
        let proof_seed=ProofSeed::new();let client_seed=proof_seed.seed();let user=NormalizedString::new(&self.username).map_err(|_|"invalid account name")?;let (proof,crypto)=proof_seed.into_client_header_crypto(&user,key,seed);
        stream.set_nonblocking(true).map_err(|_|"realm socket failed")?;let write_socket=stream.try_clone().map_err(|_|"realm socket failed")?;let (encrypt,decrypt)=crypto.split();
        let mut writer=Writer{stream:Some(write_socket),encrypter:None,chat_language:messages::LANGUAGE_COMMON,preview:Vec::new()};
        writer.send(opcode::CMSG_AUTH_SESSION,&messages::auth_session(u32::from(engine_protocol::CLIENT_BUILD),&self.username,client_seed,&proof,&messages::STOCK_SECURE_ADDONS)).map_err(|_|"realm authentication send failed")?;writer.encrypter=Some(encrypt);
        self.writer=Some(writer);self.wire=Some(Wire{stream,decrypter:decrypt,buffer:Vec::new(),body:None});self.realm=Some(index);self.phase="REALM_AUTH";self.last_ping=Instant::now();self.clock=ping::Clock::default();Ok(())
    }
    fn poll(&mut self)->Result<Value,String>{
        let mut events=Vec::new();let mut response_bytes=0;
        for _ in 0..128{
            let Some(wire)=self.wire.as_mut() else{break};let packet=match wire.packet(){Ok(p)=>p,Err(error)=>{self.reset_world();events.push(json!({"kind":"Disconnected","data":{"reason":error}}));break;}};
            let Some((op,body))=packet else{break};
            if op==opcode::SMSG_WARDEN_DATA{self.reset_world();events.push(json!({"kind":"LoginFailed","data":{"reason":"This server requires Warden, which upstream does not implement","terminal":true}}));break;}
            match messages::parse_server_with_tail(op,&body){
                Ok((packet,tail))=>{
                    match &packet {
                        ServerPacket::AuthResponse{result,queue_position,..} if self.phase=="REALM_AUTH"||self.phase=="QUEUE"=>{
                            if *result==messages::AUTH_OK{self.queue=None;self.phase="ROSTER_LOADING";self.writer.as_mut().unwrap().send(opcode::CMSG_CHAR_ENUM,&[]).map_err(|_|"roster request failed")?;}
                            else if *result==messages::AUTH_WAIT_QUEUE{self.phase="QUEUE";self.queue=*queue_position;events.push(json!({"kind":"LoginQueued","data":{"position":queue_position}}));}
                            else{let code=*result;self.reset_world();events.push(json!({"kind":"LoginFailed","data":{"code":code,"server":"WORLD"}}));}
                        },
                        ServerPacket::CharEnum{characters}=>{if characters.len()>64{self.reset_world();return Err("character roster capacity exceeded".into());}self.characters=characters.clone();self.phase="CHARACTERS";},
                        ServerPacket::Pong{sequence}=>self.clock.record(*sequence),
                        ServerPacket::CharCreate{result}|ServerPacket::CharDelete{result}=>{
                            let action=if matches!(&packet,ServerPacket::CharCreate{..}){"Create"}else{"Delete"};events.push(json!({"kind":"CharActionResult","data":{"action":action,"code":result}}));self.phase="CHARACTERS";
                            if *result==messages::CHAR_CREATE_SUCCESS||*result==messages::CHAR_DELETE_SUCCESS{self.phase="ROSTER_LOADING";self.writer.as_mut().unwrap().send(opcode::CMSG_CHAR_ENUM,&[]).map_err(|_|"roster request failed")?;}},
                        ServerPacket::LoginVerifyWorld{..}=>self.phase="WORLD",
                        ServerPacket::LogoutComplete|ServerPacket::CharacterLoginFailed{..}=>{self.self_guid=None;self.phase="ROSTER_LOADING";self.writer.as_mut().unwrap().send(opcode::CMSG_CHAR_ENUM,&[]).map_err(|_|"roster request failed")?;},
                        _=>{}
                    }
                    let decoded=engine_protocol::decode(packet).to_json();response_bytes+=decoded.to_string().len();if response_bytes>4*1024*1024{self.reset_world();return Err("decoded event capacity exceeded".into());}
                    events.push(json!({"opcode":op,"events":decoded,"tail_bytes":tail}));
                },Err(_)=>events.push(json!({"kind":"PacketDropped","data":{"opcode":op,"body_bytes":body.len()}}))
            }
        }
        if self.writer.is_some()&&self.last_ping.elapsed()>=Duration::from_secs(30){self.clock.sequence=self.clock.sequence.wrapping_add(1);self.clock.sent_at=Some(Instant::now());self.writer.as_mut().unwrap().ping(self.clock.sequence,self.clock.last_rtt_ms.unwrap_or(0)).map_err(|_|"keepalive failed")?;self.last_ping=Instant::now();}
        Ok(json!({"state":self.state(),"packets":events}))
    }
    fn request(&mut self,v:&Value)->Result<Value,String>{
        match v["op"].as_str().unwrap_or("") {
            "ping"=>Ok(json!({"abi":1})),"state"=>Ok(self.state()),
            "catalog"=>Ok(json!({"commands":verbs::COMMANDS,"types":values::PROTOCOL_TYPES,"records":values::layouts(),"build":engine_protocol::CLIENT_BUILD})),
            "auth"=>{
                if self.logon.is_some()||self.wire.is_some(){return Err("disconnect before changing login target".into());}
                let host=v["host"].as_str().filter(|s|!s.is_empty()&&s.len()<=253&&!s.contains(char::is_whitespace)).ok_or("invalid login server")?;
                let user=v["username"].as_str().ok_or("account name required")?;let pass=v["password"].as_str().ok_or("password required")?;
                if user.is_empty()||user.len()>16||pass.is_empty()||pass.len()>16{return Err("account and password require 1 to 16 characters".into());}
                self.phase="AUTHENTICATING";
                match engine_protocol::logon(host,user,pass){Ok(logon)=>{if logon.realms.len()>1024{return Err("realm list capacity exceeded".into());}self.logon=Some(logon);self.username=user.to_uppercase();self.phase="REALMS";Ok(self.state())},Err(e)=>{self.phase="LOGIN";if let Some(reject)=e.downcast_ref::<engine_protocol::AuthReject>(){Err(format!("login refused: result {}",reject.code))}else{Err("login connection or authentication failed".into())}}}
            },
            "refresh_realms"=>{let l=self.logon.as_mut().ok_or("login required")?;l.refresh_realms(Duration::from_secs(5));Ok(self.state())},
            "connect_realm"=>{let index=FromJson::from_json(&v["index"])?;self.realm_connect(index)?;Ok(self.state())},
            "back_realms"=>{self.reset_world();Ok(self.state())},
            "disconnect"=>{self.reset_world();self.logon=None;self.username.clear();self.phase="LOGIN";Ok(self.state())},
            "create_character"=>{if self.phase!="CHARACTERS"{return Err("character select required".into());}let req:messages::CharCreateReq=FromJson::from_json(&v["character"])?;if req.name.is_empty()||req.name.len()>24||req.name.contains('\0'){return Err("invalid character name".into());}self.writer.as_mut().unwrap().send(opcode::CMSG_CHAR_CREATE,&messages::char_create(&req)).map_err(|_|"character create send failed")?;self.phase="CHARACTER_ACTION";Ok(self.state())},
            "delete_character"=>{if self.phase!="CHARACTERS"{return Err("character select required".into());}let guid=FromJson::from_json(&v["guid"])?;if !self.characters.iter().any(|c|c.guid==guid){return Err("unknown character".into());}self.writer.as_mut().unwrap().send(opcode::CMSG_CHAR_DELETE,&messages::full_guid(guid)).map_err(|_|"character delete send failed")?;self.phase="CHARACTER_ACTION";Ok(self.state())},
            "enter_world"=>{if self.phase!="CHARACTERS"{return Err("character select required".into());}let guid=FromJson::from_json(&v["guid"])?;let race=self.characters.iter().find(|c|c.guid==guid).ok_or("unknown character")?.race;
                let writer=self.writer.as_mut().unwrap();writer.chat_language=if matches!(race,2|5|6|8){messages::LANGUAGE_ORCISH}else{messages::LANGUAGE_COMMON};writer.send(opcode::CMSG_PLAYER_LOGIN,&messages::full_guid(guid)).map_err(|_|"player login send failed")?;writer.set_active_mover(guid).map_err(|_|"active mover send failed")?;self.self_guid=Some(guid);self.phase="WORLD_LOADING";Ok(self.state())},
            "poll"=>self.poll(),
            "command"=>{if !matches!(self.phase,"WORLD"|"WORLD_LOADING"|"CHARACTERS"){return Err("active world session required".into());}verbs::dispatch(self.writer.as_mut().ok_or("world socket unavailable")?,v)?;Ok(Value::Null)},
            "preview_command"=>{let mut w=Writer{stream:None,encrypter:None,chat_language:messages::LANGUAGE_COMMON,preview:Vec::new()};verbs::dispatch(&mut w,v)?;Ok(json!({"packets":w.preview}))},
            "decode_packet"=>{let op=FromJson::from_json(&v["opcode"])?;let body:Vec<u8>=FromJson::from_json(&v["body"])?;let (packet,tail)=messages::parse_server_with_tail(op,&body).map_err(|_|"original packet decode failed")?;Ok(json!({"packet":packet.to_json(),"events":engine_protocol::decode(packet).to_json(),"tail_bytes":tail}))},
            "auth_challenge"=>{let username=v["username"].as_str().filter(|s|s.len()<=16).ok_or("invalid account name")?;let mut bytes=Vec::new();auth::write_logon_challenge(&mut bytes,&username.to_uppercase(),engine_protocol::CLIENT_BUILD).map_err(|_|"challenge build failed")?;Ok(json!({"bytes":bytes}))},
            _=>Err("unknown client operation".into())
        }
    }
}
#[no_mangle] pub extern "C" fn ggc_abi_version()->u32{1}
#[no_mangle] pub extern "C" fn ggc_create()->*mut std::ffi::c_void{Box::into_raw(Box::new(Client::new())).cast()}
#[no_mangle] pub unsafe extern "C" fn ggc_destroy(handle:*mut std::ffi::c_void){if !handle.is_null(){let mut c=Box::from_raw(handle.cast::<Client>());c.reset_world();}}
#[no_mangle] pub unsafe extern "C" fn ggc_request(handle:*mut std::ffi::c_void,data:*const u8,length:usize)->i32{
    if handle.is_null()||data.is_null()||length>65536{return -1;}let c=&mut *handle.cast::<Client>();
    let result=catch_unwind(AssertUnwindSafe(||{let v:Value=serde_json::from_slice(slice::from_raw_parts(data,length)).map_err(|_|"invalid client request".to_owned())?;c.request(&v)}));
    let response=match result{Ok(Ok(v))=>json!({"ok":true,"result":v}),Ok(Err(error))=>json!({"ok":false,"error":error}),Err(_)=>json!({"ok":false,"error":"client operation failed"})};
    c.response=serde_json::to_vec(&response).unwrap_or_default();if c.response.len()>MAX_MESSAGE{c.response=b"{\"ok\":false,\"error\":\"client response capacity exceeded\"}".to_vec();}0
}
#[no_mangle] pub unsafe extern "C" fn ggc_response(handle:*mut std::ffi::c_void,length:*mut usize)->*const u8{if handle.is_null()||length.is_null(){return std::ptr::null();}let c=&*handle.cast::<Client>();*length=c.response.len();c.response.as_ptr()}

#[cfg(test)]mod tests;
