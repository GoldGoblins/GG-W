//! Finite encrypted socket fixtures, always loopback and synthetic session keys.
use super::*;
use std::net::TcpListener;
use engine_srp::vanilla_header::HeaderCrypto;
struct Peer{stream:TcpStream,encrypt:EncrypterHalf,decrypt:DecrypterHalf}
fn pair()->(Client,Peer){
    let listener=TcpListener::bind("127.0.0.1:0").unwrap();let client=TcpStream::connect(listener.local_addr().unwrap()).unwrap();let (server,_)=listener.accept().unwrap();
    client.set_nonblocking(true).unwrap();client.set_nodelay(true).unwrap();server.set_nodelay(true).unwrap();server.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
    let (encrypt,decrypt)=HeaderCrypto::from_session_key([7;40]).split();let (se,sd)=HeaderCrypto::from_session_key([7;40]).split();
    let mut c=Client::new();c.writer=Some(Writer{stream:Some(client.try_clone().unwrap()),encrypter:Some(encrypt),chat_language:messages::LANGUAGE_COMMON,preview:vec![]});c.wire=Some(Wire{stream:client,decrypter:decrypt,buffer:vec![],body:None});c.phase="REALM_AUTH";
    (c,Peer{stream:server,encrypt:se,decrypt:sd})
}
impl Peer{
    fn framed(&mut self,op:u16,body:&[u8])->Vec<u8>{let size=((body.len()+2) as u16).to_be_bytes();let op=op.to_le_bytes();let mut h=vec![size[0],size[1],op[0],op[1]];self.encrypt.encrypt(&mut h);h.extend(body);h}
    fn send(&mut self,op:u16,body:&[u8]){let bytes=self.framed(op,body);self.stream.write_all(&bytes).unwrap();}
    fn receive(&mut self)->(u16,Vec<u8>){let mut h=[0;6];self.stream.read_exact(&mut h).unwrap();self.decrypt.decrypt(&mut h);let size=u16::from_be_bytes([h[0],h[1]]) as usize;let op=u32::from_le_bytes(h[2..].try_into().unwrap());let mut body=vec![0;size-4];self.stream.read_exact(&mut body).unwrap();(op as u16,body)}
}
fn drain(c:&mut Client)->Value{let deadline=Instant::now()+Duration::from_secs(2);loop{let v=c.poll().unwrap();if !v["packets"].as_array().unwrap().is_empty(){return v;}assert!(Instant::now()<deadline);std::thread::sleep(Duration::from_millis(1));}}
fn roster(guid:u64)->Vec<u8>{let mut b=vec![1];b.extend(guid.to_le_bytes());b.extend(b"Fixture\0");b.extend([1,1,0,0,0,0,0,0,10]);b.extend(700u32.to_le_bytes());b.extend(0u32.to_le_bytes());b.extend([0;12]);b.extend([0;9]);b.extend([0;12]);b.extend([0;100]);b}

#[test]fn fragmented_headers_bodies_and_cipher_state_survive_multiple_packets(){
    let (mut c,mut p)=pair();let bytes=p.framed(opcode::SMSG_AUTH_RESPONSE,&[messages::AUTH_OK]);
    p.stream.write_all(&bytes[..3]).unwrap();assert!(c.poll().unwrap()["packets"].as_array().unwrap().is_empty());
    p.stream.write_all(&bytes[3..4]).unwrap();assert!(c.poll().unwrap()["packets"].as_array().unwrap().is_empty());
    p.stream.write_all(&bytes[4..]).unwrap();assert_eq!(drain(&mut c)["state"]["phase"],"ROSTER_LOADING");assert_eq!(p.receive().0,opcode::CMSG_CHAR_ENUM);
    p.send(opcode::SMSG_CHAR_ENUM,&roster(u64::MAX-3));assert_eq!(drain(&mut c)["state"]["characters"][0]["guid"],(u64::MAX-3).to_string());
    p.send(opcode::SMSG_PONG,&9u32.to_le_bytes());assert!(drain(&mut c)["packets"].as_array().unwrap().len()>0);
}
#[test]fn queue_create_world_logout_and_character_relist_keep_same_connection(){
    let (mut c,mut p)=pair();let mut q=vec![messages::AUTH_WAIT_QUEUE];q.extend([0;9]);q.extend(17u32.to_le_bytes());p.send(opcode::SMSG_AUTH_RESPONSE,&q);assert_eq!(drain(&mut c)["state"]["queue"],17);
    p.send(opcode::SMSG_AUTH_RESPONSE,&[messages::AUTH_OK]);drain(&mut c);p.receive();let guid=u64::MAX-3;p.send(opcode::SMSG_CHAR_ENUM,&roster(guid));drain(&mut c);
    let create=json!({"op":"create_character","character":{"name":"New","race":1,"class":1,"gender":0,"skin":0,"face":0,"hair_style":0,"hair_color":0,"facial_hair":0,"outfit_id":0}});
    assert_eq!(c.request(&create).unwrap()["phase"],"CHARACTER_ACTION");assert_eq!(p.receive().0,opcode::CMSG_CHAR_CREATE);
    p.send(opcode::SMSG_CHAR_CREATE,&[messages::CHAR_CREATE_SUCCESS]);assert_eq!(drain(&mut c)["state"]["phase"],"ROSTER_LOADING");assert_eq!(p.receive().0,opcode::CMSG_CHAR_ENUM);p.send(opcode::SMSG_CHAR_ENUM,&roster(guid));drain(&mut c);
    assert_eq!(c.request(&json!({"op":"enter_world","guid":guid.to_string()})).unwrap()["phase"],"WORLD_LOADING");assert_eq!(p.receive().0,opcode::CMSG_PLAYER_LOGIN);assert_eq!(p.receive().0,opcode::CMSG_SET_ACTIVE_MOVER);
    p.send(opcode::SMSG_LOGIN_VERIFY_WORLD,&[0;20]);assert_eq!(drain(&mut c)["state"]["phase"],"WORLD");
    c.request(&json!({"op":"command","command":"logout_request"})).unwrap();assert_eq!(p.receive().0,opcode::CMSG_LOGOUT_REQUEST);p.send(opcode::SMSG_LOGOUT_COMPLETE,&[]);assert_eq!(drain(&mut c)["state"]["phase"],"ROSTER_LOADING");assert_eq!(p.receive().0,opcode::CMSG_CHAR_ENUM);
}
#[test]fn unknown_packets_can_be_dropped_but_warden_and_bad_headers_close(){
    let (mut c,mut p)=pair();p.send(0xffff,&[1,2,3]);let v=drain(&mut c);assert_eq!(v["packets"][0]["opcode"],0xffff);assert!(c.wire.is_some());
    p.send(opcode::SMSG_CHAR_ENUM,&[1]);assert_eq!(drain(&mut c)["packets"][0]["kind"],"PacketDropped");assert!(c.wire.is_some());
    p.send(opcode::SMSG_WARDEN_DATA,&[]);assert_eq!(drain(&mut c)["state"]["phase"],"LOGIN");assert!(c.wire.is_none());
    let (mut c,mut p)=pair();let mut header=[0,1,0,0];p.encrypt.encrypt(&mut header);p.stream.write_all(&header).unwrap();assert_eq!(drain(&mut c)["packets"][0]["kind"],"Disconnected");assert!(c.wire.is_none());
}
#[test]fn guid_strings_preserve_all_bits_and_unsafe_numbers_are_rejected(){
    let mut c=Client::new();let v=c.request(&json!({"op":"preview_command","command":"set_active_mover","guid":u64::MAX.to_string()})).unwrap();assert_eq!(v["packets"][0]["body"],json!([255,255,255,255,255,255,255,255]));
    assert!(c.request(&json!({"op":"preview_command","command":"set_active_mover","guid":u64::MAX})).is_err());
}
