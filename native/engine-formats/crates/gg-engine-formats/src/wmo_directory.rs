//! Bounded group headers and MODR/MOLR, without inflating geometry sectors.
use std::io::{Read,Seek,SeekFrom};
use std::path::Path;

fn metadata<R:Read+Seek>(file:&mut R,size:u64)->Result<Vec<u8>,String>{
    if size>512*1024*1024{return Err("WMO group source capacity exceeded".into());}
    let mut at=0;let mut chunks=0;
    while at+8<=size{
        chunks+=1;if chunks>8192{return Err("WMO metadata chunk capacity exceeded".into());}
        file.seek(SeekFrom::Start(at)).map_err(|e|e.to_string())?;
        let mut header=[0u8;8];file.read_exact(&mut header).map_err(|e|e.to_string())?;
        let length=u32::from_le_bytes(header[4..].try_into().unwrap()) as u64;
        let start=at+8;let end=(start+length).min(size);
        if &header[..4]==b"PGOM"{
            let take=(end-start).min(68) as usize;
            if take<40{return Err("invalid WMO group header".into());}
            let mut payload=vec![0;take];file.read_exact(&mut payload).map_err(|e|e.to_string())?;
            let mut pos=start+68;
            while pos+8<=end{
                chunks+=1;if chunks>8192{return Err("WMO metadata chunk capacity exceeded".into());}
                file.seek(SeekFrom::Start(pos)).map_err(|e|e.to_string())?;
                let mut h=[0u8;8];file.read_exact(&mut h).map_err(|e|e.to_string())?;
                let n=u32::from_le_bytes(h[4..].try_into().unwrap()) as u64;
                let next=(pos+8+n).min(end);
                if &h[..4]==b"RDOM"||&h[..4]==b"RLOM"{
                    let cap=if &h[..4]==b"RDOM"{16384}else{128};
                    let actual=(next-pos-8) as usize;
                    if n as usize>cap||actual!=n as usize||actual%2!=0{return Err("WMO reference metadata capacity exceeded".into());}
                    payload.extend_from_slice(&h);let offset=payload.len();payload.resize(offset+actual,0);
                    file.read_exact(&mut payload[offset..]).map_err(|e|e.to_string())?;
                }
                pos=next;
            }
            let mut result=b"PGOM".to_vec();result.extend_from_slice(&(payload.len() as u32).to_le_bytes());result.extend(payload);return Ok(result);
        }
        at=end;
    }
    Err("invalid WMO group header".into())
}

pub fn read(root:&Path,path:&Path,group:u32,entry:Option<&str>,chain:Option<&engine_formats_core::Chain>)->Result<Vec<u8>,String>{
    if path.is_file(){
        let real=path.canonicalize().map_err(|e|e.to_string())?;
        if !real.starts_with(root){return Err("WMO group outside permitted root".into());}
        let mut file=std::fs::File::open(real).map_err(|e|e.to_string())?;let size=file.metadata().map_err(|e|e.to_string())?.len();return metadata(&mut file,size);
    }
    let entry=entry.ok_or("WMO group missing")?;
    if entry.len()>1024||entry.starts_with('/')||entry.contains('\\')||entry.split('/').any(|p|p==".."||p.is_empty())||!entry.to_ascii_lowercase().ends_with(".wmo"){return Err("invalid WMO archive entry".into());}
    let source=Path::new(entry);let name=source.with_file_name(format!("{}_{group:03}.wmo",source.file_stem().ok_or("invalid WMO archive entry")?.to_string_lossy())).to_string_lossy().to_string();
    let archive=chain.ok_or("WMO group missing")?.archive_for(&name).map_err(|e|e.to_string())?;
    let size=archive.file_size(&name).ok_or("WMO group missing")? as u64;
    let mut file=archive.open_file(&name).map_err(|e|e.to_string())?;metadata(&mut file,size)
}
