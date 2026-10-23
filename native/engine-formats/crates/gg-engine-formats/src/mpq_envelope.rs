//! Allocation guards around the unchanged MPQ reader's private index/sector internals.
//! The original Storm implementation is included unchanged; no second crypto is invented.
#[path = "../../engine-mpq/src/crypto.rs"]
mod crypto;
use super::error;
use std::{collections::HashMap,fs::{File,Metadata},io::{Read,Seek,SeekFrom},path::{Path,PathBuf},time::SystemTime};
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;

const MAX_INDEX_ROWS:usize=262144;
const MAX_CHAIN_INDICES:usize=64*1024*1024;
const MAX_HEADER_SEARCH:u64=1024*1024;
const MAX_SECTOR:usize=32*1024*1024;
const PACKED_SLOP:usize=64*1024;
const PACKED_ENTRY_SLOP:u64=4*1024*1024;
const MAX_OFFSETS:usize=(32*1024*1024/512+1)*4;

fn word(bytes:&[u8],at:usize)->u32{u32::from_le_bytes(bytes[at..at+4].try_into().unwrap())}
fn read_at(file:&mut File,at:u64,size:usize)->Result<Vec<u8>,String>{
    file.seek(SeekFrom::Start(at)).map_err(error)?;
    let mut bytes=vec![0u8;size];file.read_exact(&mut bytes).map_err(error)?;Ok(bytes)
}
fn physical(at:u64,size:u64,length:u64)->Result<(),String>{
    if at.checked_add(size).is_none_or(|end|end>length){return Err("MPQ envelope physical bounds exceeded".into());}Ok(())
}
#[derive(PartialEq,Eq)]
struct Identity{length:u64,modified:Option<SystemTime>,#[cfg(unix)]device:u64,#[cfg(unix)]inode:u64}
impl Identity{fn new(m:&Metadata)->Self{Self{length:m.len(),modified:m.modified().ok(),#[cfg(unix)]device:m.dev(),#[cfg(unix)]inode:m.ino()}}}
struct Header{offset:u64,raw:[u8;32],identity:Identity,sector:usize,hash_at:u64,block_at:u64,hash_rows:usize,block_rows:usize}
impl Header{
    fn load(path:&Path)->Result<Self,String>{
        let mut file=File::open(path).map_err(error)?;let identity=Identity::new(&file.metadata().map_err(error)?);
        let mut at=0u64;let mut found=None;
        while at+4<=identity.length.min(MAX_HEADER_SEARCH){
            let bytes=read_at(&mut file,at,4)?;
            match word(&bytes,0){
                0x1a51504d=>{found=Some(at);break;},
                0x1b51504d=>{physical(at,12,identity.length)?;let bytes=read_at(&mut file,at+4,8)?;found=at.checked_add(word(&bytes,4) as u64);break;},
                _=>at+=512,
            }
        }
        let offset=found.ok_or("MPQ envelope header unavailable within search capacity")?;
        physical(offset,32,identity.length)?;let raw:[u8;32]=read_at(&mut file,offset,32)?.try_into().unwrap();
        if word(&raw,0)!=0x1a51504d{return Err("invalid MPQ envelope signature".into());}
        let shift=u16::from_le_bytes(raw[14..16].try_into().unwrap());
        if shift>16{return Err("MPQ sector size capacity exceeded".into());}
        let sector=512usize<<shift;
        if sector>MAX_SECTOR{return Err("MPQ sector size capacity exceeded".into());}
        let hash_rows=word(&raw,24) as usize;let block_rows=word(&raw,28) as usize;
        if hash_rows>MAX_INDEX_ROWS||block_rows>MAX_INDEX_ROWS{return Err("MPQ index capacity exceeded".into());}
        let hash_at=offset.checked_add(word(&raw,16) as u64).ok_or("MPQ index position capacity exceeded")?;
        let block_at=offset.checked_add(word(&raw,20) as u64).ok_or("MPQ index position capacity exceeded")?;
        physical(hash_at,(hash_rows*16) as u64,identity.length)?;physical(block_at,(block_rows*16) as u64,identity.length)?;
        Ok(Self{offset,raw,identity,sector,hash_at,block_at,hash_rows,block_rows})
    }
    fn bytes(&self)->usize{(self.hash_rows+self.block_rows)*16}
}
fn index(file:&mut File,at:u64,rows:usize,name:&str)->Result<Vec<u32>,String>{
    let bytes=read_at(file,at,rows*16)?;
    let mut words=bytes.chunks_exact(4).map(|b|u32::from_le_bytes(b.try_into().unwrap())).collect::<Vec<_>>();
    crypto::decrypt_block(&mut words,crypto::hash_string(name,crypto::hash_type::FILE_KEY));Ok(words)
}
pub(crate) struct Envelope{header:Header,hashes:Vec<u32>,blocks:Vec<u32>}
impl Envelope{
    fn load(path:&Path,header:Header)->Result<Self,String>{
        let mut file=File::open(path).map_err(error)?;
        if Identity::new(&file.metadata().map_err(error)?)!=header.identity{return Err("MPQ source changed during mount".into());}
        let hashes=index(&mut file,header.hash_at,header.hash_rows,"(hash table)")?;
        let blocks=index(&mut file,header.block_at,header.block_rows,"(block table)")?;
        Ok(Self{header,hashes,blocks})
    }
    fn block(&self,name:&str)->Option<&[u32]>{
        let len=self.header.hash_rows;if len==0{return None;}
        let start=(crypto::hash_string(name,crypto::hash_type::TABLE_OFFSET)&(len-1) as u32) as usize;
        let a=crypto::hash_string(name,crypto::hash_type::NAME_A);let b=crypto::hash_string(name,crypto::hash_type::NAME_B);
        for n in 0..len{
            let row=&self.hashes[((start+n)%len)*4..][..4];let block=row[3];
            if block==0xffffffff{return None;}if block==0xfffffffe{continue;}
            if row[0]==a&&row[1]==b{return self.blocks.get(block as usize*4..).and_then(|v|v.get(..4));}
        }None
    }
    pub(crate) fn guard(&self,path:&Path,name:&str,original_size:usize)->Result<(),String>{
        let mut file=File::open(path).map_err(error)?;
        if Identity::new(&file.metadata().map_err(error)?)!=self.header.identity{return Err("MPQ source changed since mount".into());}
        if read_at(&mut file,self.header.offset,32)?.as_slice()!=self.header.raw{return Err("MPQ header identity changed since mount".into());}
        if index(&mut file,self.header.hash_at,self.header.hash_rows,"(hash table)")?!=self.hashes||index(&mut file,self.header.block_at,self.header.block_rows,"(block table)")?!=self.blocks{
            return Err("MPQ index identity changed since mount".into());
        }
        let block=self.block(name).ok_or("MPQ envelope entry missing")?;
        let size=block[2] as usize;let flags=block[3];
        if size!=original_size{return Err("MPQ cached winning entry identity mismatch".into());}
        // Original open_file rejects these before any sector allocation; retain that error path.
        if flags&0x00010000!=0||flags&0x01000000!=0||flags&0x02000000!=0||flags&0x80000000==0{return Ok(());}
        let base=self.header.offset.checked_add(block[0] as u64).ok_or("MPQ entry position capacity exceeded")?;
        if flags&0x300==0{return physical(base,size as u64,self.header.identity.length);}
        let sectors=size.div_ceil(self.header.sector);
        let table_bytes=(sectors+1).checked_mul(4).ok_or("MPQ offset table capacity exceeded")?;
        if table_bytes>MAX_OFFSETS{return Err("MPQ offset table capacity exceeded".into());}
        physical(base,table_bytes as u64,self.header.identity.length)?;
        let bytes=read_at(&mut file,base,table_bytes)?;
        let mut total_packed=0u64;
        for i in 0..sectors{
            let start=word(&bytes,i*4) as u64;let end=word(&bytes,(i+1)*4) as u64;
            let packed=end.checked_sub(start).ok_or("MPQ packed sector offsets reversed")?;
            let expected=(size-i*self.header.sector).min(self.header.sector);
            if packed>expected.saturating_add(PACKED_SLOP) as u64{return Err("MPQ packed sector capacity exceeded".into());}
            if packed==0||start<table_bytes as u64{return Err("invalid MPQ packed sector offset".into());}
            total_packed=total_packed.checked_add(packed).ok_or("MPQ aggregate packed input capacity exceeded")?;
            if total_packed>size as u64+PACKED_ENTRY_SLOP{return Err("MPQ aggregate packed input capacity exceeded".into());}
            physical(base.checked_add(start).ok_or("MPQ packed sector position capacity exceeded")?,packed,self.header.identity.length)?;
            if end>block[1] as u64{return Err("MPQ packed entry bounds exceeded".into());}
        }Ok(())
    }
}
pub(crate) fn mount(files:&[PathBuf])->Result<HashMap<PathBuf,Envelope>,String>{
    // Check all header counts and the aggregate BEFORE decrypting or opening an original index.
    let mut headers=Vec::with_capacity(files.len());let mut total=0usize;
    for path in files{
        let header=Header::load(path)?;total+=header.bytes();
        if total>MAX_CHAIN_INDICES{return Err("MPQ aggregate index capacity exceeded".into());}
        headers.push((path.clone(),header));
    }
    headers.into_iter().map(|(path,header)|Envelope::load(&path,header).map(|guard|(path,guard))).collect()
}
