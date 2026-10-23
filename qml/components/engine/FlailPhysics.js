.pragma library

// A short world-space Verlet chain. Presentation follows the existing combat
// result; moving its links never creates a second damage or targeting system.
var STEP = 1 / 120
function add(a,b) { return [a[0]+b[0],a[1]+b[1],a[2]+b[2]] }
function sub(a,b) { return [a[0]-b[0],a[1]-b[1],a[2]-b[2]] }
function mul(a,s) { return [a[0]*s,a[1]*s,a[2]*s] }
function dot(a,b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2] }
function norm(a) { return Math.sqrt(dot(a,a)) }
function create(anchor,length,links) {
    var s={points:[],previous:[],anchor:anchor.slice(),length:length,
        links:Math.max(2,Math.min(12,links)),accumulator:0,steps:0}
    for(var i=0;i<=s.links;++i) {
        var t=i/s.links
        var p=add(anchor,[length*t*.10,-length*t*Math.sqrt(.99),0])
        s.points.push(p);s.previous.push(p.slice())
    }
    return s
}
function shaftOffset(point,a,b) {
    var ab=sub(b,a),den=dot(ab,ab)
    var t=den>1e-12 ? Math.max(0,Math.min(1,dot(sub(point,a),ab)/den)) : 0
    var closest=add(a,mul(ab,t))
    return {closest:closest,offset:sub(point,closest)}
}
function avoidShaft(point,a,b,radius,previousPoint,previousShaft) {
    var contact=shaftOffset(point,a,b),closest=contact.closest,d=contact.offset,distance=norm(d)
    // Sweep relative to the moving handle. A quick hand movement must push
    // the ball from the side it contacted, instead of tunnelling through the
    // shaft and trapping a stretched chain on its far side.
    if(previousPoint && previousShaft) {
        var old=shaftOffset(previousPoint,previousShaft[0],previousShaft[1]).offset
        var travel=sub(d,old),den=dot(travel,travel)
        var t=den>1e-12 ? Math.max(0,Math.min(1,-dot(old,travel)/den)) : 0
        if(dot(old,d)<0 && norm(old)>radius*.8 && norm(add(old,mul(travel,t)))<radius)
            return add(closest,mul(old,radius/norm(old)))
    }
    if(distance>=radius)return point
    return add(closest,distance>1e-8 ? mul(d,radius/distance) : [radius,0,0])
}
function step(s,anchor,dt,shaft,headRadius,shaftRadius) {
    if(!isFinite(dt)||dt<=0)return s
    if(norm(sub(anchor,s.anchor))>Math.max(2,s.length*4))
        return create(anchor,s.length,s.links)
    dt=Math.min(.08,dt);s.accumulator=Math.min(.08,s.accumulator+dt)
    var count=Math.floor((s.accumulator+1e-9)/STEP)
    if(!count)return s
    s.accumulator-=count*STEP
    var oldAnchor=s.anchor.slice(),delta=sub(anchor,oldAnchor)
    var segment=s.length/s.links
    var oldShaft=s.shaft || shaft,previousShaft=oldShaft
    for(var tick=0;tick<count;++tick) {
        var fixed=add(oldAnchor,mul(delta,(tick+1)/count))
        var currentShaft=shaft && oldShaft ? [
            add(oldShaft[0],mul(sub(shaft[0],oldShaft[0]),(tick+1)/count)),
            add(oldShaft[1],mul(sub(shaft[1],oldShaft[1]),(tick+1)/count))] : null
        for(var i=1;i<=s.links;++i) {
            var p=s.points[i],velocity=mul(sub(p,s.previous[i]),.991)
            s.previous[i]=p.slice()
            s.points[i]=add(add(p,velocity),[0,-9.81*STEP*STEP,0])
        }
        // The ball is heavier than each link. Weighted constraints preserve
        // inertia while keeping the root pinned to the moving attachment eye.
        for(var iteration=0;iteration<128;++iteration) {
            s.points[0]=fixed.slice()
            for(var i=1;i<=s.links;++i) {
                var d=sub(s.points[i],s.points[i-1]),distance=norm(d)
                if(distance<1e-10)d=[0,-segment,0],distance=segment
                var left=i===1 ? 0 : 1,right=i===s.links ? .18 : 1
                var correction=mul(d,(distance-segment)/distance/(left+right))
                if(left)s.points[i-1]=add(s.points[i-1],mul(correction,left))
                s.points[i]=sub(s.points[i],mul(correction,right))
            }
            if(currentShaft && currentShaft.length===2) {
                for(var i=1;i<=s.links;++i)
                    s.points[i]=avoidShaft(s.points[i],currentShaft[0],currentShaft[1],
                        shaftRadius+(i===s.links ? headRadius : .009),s.previous[i],previousShaft)
            }
            var error=0
            for(var i=1;i<=s.links;++i)
                error=Math.max(error,Math.abs(norm(sub(s.points[i],s.points[i-1]))-segment))
            if(error<.00015)break
        }
        s.points[0]=fixed.slice();s.steps++;previousShaft=currentShaft
    }
    s.anchor=anchor.slice();s.shaft=shaft
    return s
}
function rotationFromY(direction) {
    var length=norm(direction)
    if(length<1e-10)return [1,0,0,0]
    var d=mul(direction,1/length)
    if(d[1]<-.999999)return [0,1,0,0]
    var q=[1+d[1],d[2],0,-d[0]]
    var n=Math.sqrt(q[0]*q[0]+q[1]*q[1]+q[3]*q[3])
    return [q[0]/n,q[1]/n,0,q[3]/n]
}
function rotate(q,v) {
    var x=q[1],y=q[2],z=q[3],w=q[0]
    var t=[2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0])]
    return add(v,add(mul(t,w),[y*t[2]-z*t[1],z*t[0]-x*t[2],x*t[1]-y*t[0]]))
}
