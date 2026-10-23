//! GgEngine's lowest-group owner law, keeping physical wet grids intact.
//! Adapted from engine-formats/src/wmo.rs::resolve_shared_liquid_cells.
use engine_formats_core::LiquidMesh;
use std::collections::HashMap;
#[derive(Default)]
pub struct Owners(HashMap<(i32,i32),u32>);
impl Owners {
    pub fn draw_indices(&mut self,mesh:&LiquidMesh,group:u32)->Vec<u32>{
        let cols=mesh.grid[0] as usize;let xt=cols.saturating_sub(1);
        let keys:Vec<_>=(0..mesh.wet.len()).map(|c|{
            let (x,y)=(c%xt,c/xt);let a=mesh.positions[y*cols+x];let b=mesh.positions[(y+1)*cols+x+1];
            (((a[0]+b[0])*50.).round() as i32,((a[1]+b[1])*50.).round() as i32)
        }).collect();
        for (c,&wet) in mesh.wet.iter().enumerate(){if wet&&mesh.shared[c]{self.0.entry(keys[c]).or_insert(group);}}
        let mut draw=mesh.clone();draw.retain_cells(|c|!mesh.shared[c]||self.0.get(&keys[c])==Some(&group));draw.indices
    }
}
