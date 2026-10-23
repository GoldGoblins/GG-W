//! Original 30 s keepalive and bounded 15-sample latency policy.
use std::{collections::VecDeque,time::Instant};
#[derive(Default)]
pub struct Clock{pub sequence:u32,pub sent_at:Option<Instant>,pub last_rtt_ms:Option<u32>,samples:VecDeque<u32>}
impl Clock{
    pub fn record(&mut self,sequence:u32){
        if let Some(sent)=self.sent_at.filter(|_|sequence==self.sequence){
            self.file(sent.elapsed().as_millis().min(u128::from(u32::MAX)) as u32);
        }
    }
    fn file(&mut self,rtt:u32){self.last_rtt_ms=Some(rtt);if self.samples.len()==15{self.samples.pop_front();}self.samples.push_back(rtt);}
    pub fn average(&self)->Option<u32>{if self.samples.is_empty(){None}else{Some((self.samples.iter().map(|n|u64::from(*n)).sum::<u64>()/self.samples.len() as u64) as u32)}}
}
#[cfg(test)]mod tests{
    use super::*;
    #[test]fn ring_is_fifteen_truncating_samples(){let mut c=Clock::default();assert_eq!(c.average(),None);c.file(40);c.file(61);assert_eq!(c.average(),Some(50));for _ in 0..15{c.file(100);}assert_eq!(c.samples.len(),15);assert_eq!(c.average(),Some(100));assert_eq!(c.last_rtt_ms,Some(100));}
    #[test]fn unsolicited_pong_does_not_change_measurements(){let mut c=Clock::default();c.sequence=2;c.sent_at=Some(Instant::now());c.record(1);assert_eq!(c.average(),None);c.record(2);assert!(c.average().is_some());}
}
