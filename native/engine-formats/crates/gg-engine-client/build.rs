//! Generate typed adapters from the preserved original API, without editing it.
use std::{collections::{BTreeMap,BTreeSet},path::{Path,PathBuf}};
use quote::{quote,ToTokens};
use syn::{Item,Fields,UseTree,Type,Visibility};

fn parse(path:&Path)->syn::File{
    println!("cargo:rerun-if-changed={}",path.display());
    syn::parse_file(&std::fs::read_to_string(path).unwrap()).unwrap()
}
fn uses(tree:&UseTree,out:&mut BTreeSet<String>){
    match tree {UseTree::Path(p)=>uses(&p.tree,out),UseTree::Name(n)=>{out.insert(n.ident.to_string());},UseTree::Group(g)=>for x in &g.items{uses(x,out)},_=>{}}
}
fn files(root:&Path,out:&mut Vec<PathBuf>){
    for entry in std::fs::read_dir(root).unwrap(){let p=entry.unwrap().path();if p.is_dir(){files(&p,out)}else if p.extension().is_some_and(|x|x=="rs"){out.push(p)}}
}
fn record(fields:&Fields,read:bool)->String{
    match fields {
        Fields::Named(f)=>{
            let parts=f.named.iter().map(|f|{let n=f.ident.as_ref().unwrap().to_string();if read{format!("{n}:FromJson::from_json(&v[\"{n}\"])?")}else{format!("\"{n}\":self.{n}.to_json()")}}).collect::<Vec<_>>().join(",");
            if read{format!("Self{{{parts}}}")}else{format!("serde_json::json!({{{parts}}})")}
        },
        Fields::Unnamed(f)=>{
            let parts=(0..f.unnamed.len()).map(|i|if read{format!("FromJson::from_json(&v[{i}])?")}else{format!("self.{i}.to_json()")}).collect::<Vec<_>>().join(",");
            if read{format!("Self({parts})")}else{format!("serde_json::json!([{parts}])")}
        },Fields::Unit=>if read{"Self".into()}else{"serde_json::Value::Null".into()}
    }
}
fn main(){
    let root=Path::new("../engine-protocol/src");let dest=PathBuf::from(std::env::var("OUT_DIR").unwrap());
    let mut exports=BTreeSet::new();for item in parse(&root.join("messages/mod.rs")).items{if let Item::Use(u)=item{if matches!(u.vis,Visibility::Public(_)){uses(&u.tree,&mut exports);}}}
    let mut paths=Vec::new();files(&root.join("messages"),&mut paths);paths.sort();let mut types=BTreeMap::new();
    for path in paths {for item in parse(&path).items{match &item{Item::Struct(s) if exports.contains(&s.ident.to_string())=>{types.insert(format!("engine_protocol::messages::{}",s.ident),item);},Item::Enum(e) if exports.contains(&e.ident.to_string())=>{types.insert(format!("engine_protocol::messages::{}",e.ident),item);},_=>{}}}}
    for module in ["events.rs","wire.rs","lib.rs"]{
        for item in parse(&root.join(module)).items{
            let prefix=match module{"events.rs"=>"engine_protocol::events","wire.rs"=>"engine_protocol::wire",_=>"engine_protocol"};
            match &item{Item::Struct(s) if matches!(s.vis,Visibility::Public(_))&&!matches!(s.ident.to_string().as_str(),"Logon"|"ChallengeReply")=>{types.insert(format!("{prefix}::{}",s.ident),item);},Item::Enum(e) if matches!(e.vis,Visibility::Public(_))=>{types.insert(format!("{prefix}::{}",e.ident),item);},_=>{}}
        }
    }
    let fields=|f:&Fields|match f{
        Fields::Named(f)=>format!("serde_json::json!({{{}}})",f.named.iter().map(|p|format!("{:?}:{:?}",p.ident.as_ref().unwrap().to_string(),p.ty.to_token_stream().to_string())).collect::<Vec<_>>().join(",")),
        Fields::Unnamed(f)=>format!("serde_json::json!([{}])",f.unnamed.iter().map(|p|format!("{:?}",p.ty.to_token_stream().to_string())).collect::<Vec<_>>().join(",")),
        Fields::Unit=>"Value::Null".into()
    };
    let mut code=String::new();let mut count=0;let mut layouts=Vec::new();
    for (path,item) in types {
        match item {
            Item::Struct(s) if s.generics.params.is_empty()&&s.fields.iter().all(|f|matches!(f.vis,Visibility::Public(_)))=>{
                layouts.push(format!("serde_json::json!({{\"name\":{:?},\"fields\":{}}})",s.ident.to_string(),fields(&s.fields)));
                count+=1;code+=&format!("impl ToJson for {path}{{fn to_json(&self)->Value{{ {} }}}}\n",record(&s.fields,false));
                code+=&format!("impl FromJson for {path}{{fn from_json(v:&Value)->Result<Self,String>{{Ok({})}}}}\n",record(&s.fields,true));
            },
            Item::Enum(e)=>{
                layouts.push(format!("{{let mut variants=serde_json::Map::new();{}serde_json::json!({{\"name\":{:?},\"variants\":Value::Object(variants)}})}}",e.variants.iter().map(|v|format!("variants.insert({:?}.into(),{});",v.ident.to_string(),fields(&v.fields))).collect::<String>(),e.ident.to_string()));
                let mut to=Vec::new();let mut from=Vec::new();count+=1;
                for variant in e.variants {
                    let name=variant.ident.to_string();let (pattern,value,construct)=match &variant.fields{
                        Fields::Named(f)=>{
                            let names=f.named.iter().map(|f|f.ident.as_ref().unwrap().to_string()).collect::<Vec<_>>();
                            (format!("{{{}}}",names.join(",")),format!("serde_json::json!({{{}}})",names.iter().map(|n|format!("\"{n}\":{n}.to_json()")).collect::<Vec<_>>().join(",")),format!("{{{}}}",names.iter().map(|n|format!("{n}:FromJson::from_json(&data[\"{n}\"])?")).collect::<Vec<_>>().join(",")))
                        },Fields::Unnamed(f)=>{
                            let names=(0..f.unnamed.len()).map(|i|format!("x{i}")).collect::<Vec<_>>();
                            (format!("({})",names.join(",")),format!("serde_json::json!([{}])",names.iter().map(|n|format!("{n}.to_json()")).collect::<Vec<_>>().join(",")),format!("({})",(0..names.len()).map(|i|format!("FromJson::from_json(&data[{i}])?")).collect::<Vec<_>>().join(",")))
                        },Fields::Unit=>(String::new(),"Value::Null".into(),String::new())
                    };
                    to.push(format!("Self::{name}{pattern}=>serde_json::json!({{\"kind\":\"{name}\",\"data\":{value}}})"));
                    from.push(format!("\"{name}\"=>Ok(Self::{name}{construct})"));
                }
                code+=&format!("impl ToJson for {path}{{fn to_json(&self)->Value{{match self{{{}}}}}}}\n",to.join(","));
                code+=&format!("impl FromJson for {path}{{fn from_json(v:&Value)->Result<Self,String>{{let data=&v[\"data\"];match v.as_str().or(v[\"kind\"].as_str()).unwrap_or(\"\"){{{},_=>Err(\"invalid protocol enum\".into())}}}}}}\n",from.join(","));
            },_=>{}
        }
    }
    code+=&format!("pub const PROTOCOL_TYPES:usize={count};\n");
    code+=&format!("pub fn layouts()->Value{{Value::Array(vec![{}])}}\n",layouts.join(","));std::fs::write(dest.join("types.rs"),code).unwrap();
    let writer_dir=root.join("world/writer");let mut paths=Vec::new();files(&writer_dir,&mut paths);paths.sort();let mut dispatch=Vec::new();let mut catalog=Vec::new();let mut modules=String::new();
    for path in paths {
        if path.file_name().unwrap()=="mod.rs"{continue;}
        let ast=parse(&path);let name=path.file_stem().unwrap().to_string_lossy();let mut imports=Vec::new();let mut implementations=Vec::new();
        for item in ast.items {
            match item {
                Item::Use(u)=>{
                    let text=u.to_token_stream().to_string();
                    if !text.contains("super :: WorldWriter"){imports.push(text.replace("crate :: messages","engine_protocol :: messages").replace("crate :: world :: movement","crate :: movement"));}
                },Item::Impl(imp)=>{
                    for item in &imp.items {if let syn::ImplItem::Fn(f)=item{if !matches!(f.vis,Visibility::Public(_)){continue;}let method=f.sig.ident.to_string();let mut args=Vec::new();let mut declarations=Vec::new();let mut parameters=Vec::new();
                        for arg in &f.sig.inputs{if let syn::FnArg::Typed(arg)=arg{let syn::Pat::Ident(pat)=&*arg.pat else{panic!("unsupported writer argument")};let id=pat.ident.to_string();let ty=&arg.ty;parameters.push(format!("({id:?},{:?})",ty.to_token_stream().to_string()));
                            if ty.to_token_stream().to_string()=="Option < & str >"{
                                declarations.push(format!("let {id}:Option<String>=FromJson::from_json(&v[\"{id}\"])?;"));args.push(format!("{id}.as_deref()"));continue;
                            }
                            match &**ty{
                                Type::Reference(r)=>{
                                    let inner=&*r.elem;let is_str=inner.to_token_stream().to_string()=="str";
                                    if is_str{declarations.push(format!("let {id}:String=FromJson::from_json(&v[\"{id}\"])?;"));args.push(format!("&{id}"));}
                                    else if let Type::Slice(s)=inner{let t=&s.elem;declarations.push(format!("let {id}:Vec<{}>=FromJson::from_json(&v[\"{id}\"])?;",t.to_token_stream()));args.push(format!("&{id}"));}
                                    else{declarations.push(format!("let {id}:{}=FromJson::from_json(&v[\"{id}\"])?;",inner.to_token_stream()));args.push(format!("&{id}"));}
                                },_=>{declarations.push(format!("let {id}:{}=FromJson::from_json(&v[\"{id}\"])?;",ty.to_token_stream()));args.push(id);}
                            }
                        }}
                        dispatch.push(format!("\"{method}\"=>{{{} writer.{method}({}).map_err(|_|\"world send failed\".to_owned())?;Ok(())}}",declarations.join(""),args.join(",")));
                        catalog.push(format!("({method:?},&[{}])",parameters.join(",")));
                    }}
                    let mut imp=imp;imp.self_ty=Box::new(syn::parse_quote!(crate::Writer));implementations.push(quote!(#imp).to_string());
                },Item::Fn(f)=>implementations.push(f.to_token_stream().to_string()),_=>{}
            }
        }
        modules+=&format!("mod verbs_{name}{{{} {} }}\n",imports.join("\n"),implementations.join("\n"));
    }
    modules+=&format!("pub const COMMANDS:&[(&str,&[(&str,&str)])]=&[{}];\n",catalog.join(","));
    modules+=&format!("pub fn dispatch(writer:&mut crate::Writer,v:&Value)->Result<(),String>{{use engine_protocol::messages::*;match v[\"command\"].as_str().unwrap_or(\"\"){{{},_=>Err(\"unknown original world command\".into())}}}}",dispatch.join(","));
    std::fs::write(dest.join("verbs.rs"),modules).unwrap();
}
