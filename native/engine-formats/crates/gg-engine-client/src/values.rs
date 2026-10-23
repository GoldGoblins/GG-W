//! Local JSON traits for the unchanged original protocol types.
use serde_json::Value;
pub trait ToJson{fn to_json(&self)->Value;}
pub trait FromJson:Sized{fn from_json(v:&Value)->Result<Self,String>;}
macro_rules! scalar {($($t:ty),*)=>{$(impl ToJson for $t{fn to_json(&self)->Value{serde_json::json!(self)}}
impl FromJson for $t{fn from_json(v:&Value)->Result<Self,String>{serde_json::from_value(v.clone()).map_err(|_|"invalid protocol value".into())}})*}}
scalar!(bool,u8,u16,u32,usize,i8,i16,i32,i64,f32,f64,String);
impl ToJson for u64{fn to_json(&self)->Value{Value::String(self.to_string())}}
impl FromJson for u64{fn from_json(v:&Value)->Result<Self,String>{v.as_str().and_then(|s|s.parse().ok()).or_else(||v.as_u64().filter(|n|*n<=9_007_199_254_740_991)).ok_or("64-bit identifiers above the JavaScript integer range require decimal strings".into())}}
impl ToJson for str{fn to_json(&self)->Value{Value::String(self.into())}}
impl<T:ToJson+?Sized> ToJson for &T{fn to_json(&self)->Value{(**self).to_json()}}
impl<T:ToJson> ToJson for Box<T>{fn to_json(&self)->Value{(**self).to_json()}}
impl<T:FromJson> FromJson for Box<T>{fn from_json(v:&Value)->Result<Self,String>{T::from_json(v).map(Box::new)}}
impl<T:ToJson> ToJson for Option<T>{fn to_json(&self)->Value{self.as_ref().map(ToJson::to_json).unwrap_or(Value::Null)}}
impl<T:FromJson> FromJson for Option<T>{fn from_json(v:&Value)->Result<Self,String>{if v.is_null(){Ok(None)}else{T::from_json(v).map(Some)}}}
impl<T:ToJson> ToJson for Vec<T>{fn to_json(&self)->Value{Value::Array(self.iter().map(ToJson::to_json).collect())}}
impl<T:FromJson> FromJson for Vec<T>{fn from_json(v:&Value)->Result<Self,String>{v.as_array().filter(|a|a.len()<=65536).ok_or("invalid protocol array")?.iter().map(T::from_json).collect()}}
impl<T:ToJson,const N:usize> ToJson for [T;N]{fn to_json(&self)->Value{Value::Array(self.iter().map(ToJson::to_json).collect())}}
impl<T:FromJson,const N:usize> FromJson for [T;N]{fn from_json(v:&Value)->Result<Self,String>{let a:Vec<T>=FromJson::from_json(v)?;a.try_into().map_err(|_|"invalid protocol array length".into())}}
macro_rules! tuple {($($t:ident:$i:tt),*)=>{impl<$($t:ToJson),*> ToJson for ($($t,)*){fn to_json(&self)->Value{serde_json::json!([$((self.$i).to_json()),*])}}
impl<$($t:FromJson),*> FromJson for ($($t,)*){fn from_json(v:&Value)->Result<Self,String>{Ok(($(FromJson::from_json(&v[$i])?,)*))}}}}
tuple!(A:0,B:1);tuple!(A:0,B:1,C:2);tuple!(A:0,B:1,C:2,D:3);
impl ToJson for engine_protocol::messages::ObjectFields{fn to_json(&self)->Value{serde_json::json!({"fields":self.raw_fields().collect::<Vec<_>>().to_json(),"created_as":self.created_as().to_json()})}}
impl FromJson for engine_protocol::messages::ObjectFields{fn from_json(v:&Value)->Result<Self,String>{let pairs:Vec<(u16,u32)>=FromJson::from_json(&v["fields"])?;let fields=Self::from_pairs(&pairs);Ok(if v["created_as"].is_null(){fields}else{fields.into_created(FromJson::from_json(&v["created_as"])? )})}}
#[allow(unused_variables)]
mod original_types{use super::*;include!(concat!(env!("OUT_DIR"),"/types.rs"));}
pub use original_types::{PROTOCOL_TYPES,layouts};
