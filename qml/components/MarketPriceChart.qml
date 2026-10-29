import "." as RuntimeTheme
import QtQuick

import "MarketFormat.js" as Format

Item {
    id:root;objectName:"marketPriceChart"
    property var series:({})
    property string period:"7 dagar"
    readonly property var prices:series.prices || []
    readonly property var times:series.times || []
    readonly property bool valid:prices.length>=2 && prices.length<=600 && prices.every(function(p){return typeof p==="number" && isFinite(p) && p>=0})
    readonly property bool timed:valid && times.length===prices.length && times.every(function(t,i){return typeof t==="number" && isFinite(t) && (i===0 || t>times[i-1])})
    readonly property bool observed:series.kind==="OBSERVED_SAMPLES_NOT_OHLC"
    readonly property bool plottable:valid && (!observed || timed && times[times.length-1]-times[0]>=60)
    readonly property real low:valid ? Math.min.apply(null,prices) : 0
    readonly property real high:valid ? Math.max.apply(null,prices) : 0
    readonly property color trend:high===low ? RuntimeTheme.GGTheme.muted : valid && prices[prices.length-1]<prices[0] ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.positive
    property int hoveredIndex:-1
    function stamp(index){return timed ? new Date(times[index]*1000).toLocaleDateString(Qt.locale(),"d MMM") : ""}
    function fraction(index){return timed ? (times[index]-times[0])/(times[times.length-1]-times[0]) : index/(prices.length-1)}
    function nearest(f){if(!valid)return -1;if(!timed)return Math.max(0,Math.min(prices.length-1,Math.round(f*(prices.length-1))));var target=times[0]+f*(times[times.length-1]-times[0]),lo=0,hi=times.length-1;while(lo<hi){var mid=(lo+hi)>>1;if(times[mid]<target)lo=mid+1;else hi=mid}return lo>0 && target-times[lo-1]<times[lo]-target ? lo-1 : lo}
    onSeriesChanged:{hoveredIndex=-1;plot.requestPaint()}
    onWidthChanged:plot.requestPaint()
    onHeightChanged:plot.requestPaint()
    onHoveredIndexChanged:plot.requestPaint()
    GgFrame { property string uiColorScope: "ui.widget.MarketPriceChart.GgFrame.1";anchors.fill:parent;leftLegend:"PRIS / USD";rightLegend:root.period;borderColor:RuntimeTheme.GGTheme.line;backgroundColor:RuntimeTheme.GGTheme.canvas}
    Canvas {
        id:plot;x:12;y:24;width:Math.max(0,parent.width-84);height:Math.max(0,parent.height-56)
        onPaint:{
            var c=getContext("2d");c.reset();if(!root.plottable || width<10 || height<10)return
            var span=root.high-root.low
            function y(p){return span===0 ? height/2 : height-6-(p-root.low)*(height-12)/span}
            c.strokeStyle=RuntimeTheme.GGTheme.line;c.lineWidth=.5;c.setLineDash([2,5]);for(var grid=0;grid<=4;grid++){c.beginPath();c.moveTo(0,grid*height/4);c.lineTo(width,grid*height/4);c.stroke()}
            for(var col=0;col<=6;col++){c.beginPath();c.moveTo(col*width/6,0);c.lineTo(col*width/6,height);c.stroke()}c.setLineDash([])
            c.beginPath();for(var i=0;i<root.prices.length;i++){var x=root.fraction(i)*width;if(i===0)c.moveTo(x,y(root.prices[i]));else c.lineTo(x,y(root.prices[i]))}
            c.lineWidth=1.5;c.strokeStyle=root.trend;c.stroke();if(span>0){c.lineTo(width,height);c.lineTo(0,height);c.closePath();c.globalAlpha=.09;c.fillStyle=root.trend;c.fill();c.globalAlpha=1}
            if(root.hoveredIndex>=0 && root.hoveredIndex<root.prices.length){var hx=root.fraction(root.hoveredIndex)*width,hy=y(root.prices[root.hoveredIndex]);c.setLineDash([3,4]);c.strokeStyle=RuntimeTheme.GGTheme.muted;c.beginPath();c.moveTo(hx,0);c.lineTo(hx,height);c.stroke();c.setLineDash([]);c.beginPath();c.arc(hx,hy,3,0,Math.PI*2);c.fillStyle=RuntimeTheme.GGTheme.bright;c.fill()}
        }
        MouseArea {anchors.fill:parent;enabled:root.plottable;hoverEnabled:true;acceptedButtons:Qt.NoButton;onPositionChanged:function(mouse){root.hoveredIndex=root.nearest(Math.max(0,Math.min(1,mouse.x/Math.max(1,width))))};onExited:root.hoveredIndex=-1}
    }
    Column {x:plot.x+plot.width+8;y:plot.y+(root.high===root.low ? plot.height/2-5 : 0);spacing:Math.max(0,(plot.height-50)/4)
        Repeater {model:root.plottable ? root.high===root.low ? 1 : 5 : 0
            GGText { colorKey: "ui.MarketPriceChart.1";required property int index;text:Format.money(root.high-(root.high-root.low)*index/4);color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:9}
        }
    }
    Row {x:plot.x;y:parent.height-23;width:plot.width
        GGText { colorKey: "ui.MarketPriceChart.2";width:parent.width/2;text:root.plottable ? root.stamp(0) : "";color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:9}
        GGText { colorKey: "ui.MarketPriceChart.3";width:parent.width/2;text:root.plottable ? root.stamp(root.prices.length-1) : "";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:9}
    }
    GGText { colorKey: "ui.MarketPriceChart.4";x:20;y:34;visible:root.hoveredIndex>=0;text:root.hoveredIndex>=0 ? Format.money(root.prices[root.hoveredIndex])+"  "+root.stamp(root.hoveredIndex) : "";color:RuntimeTheme.GGTheme.bright;font.family:"monospace";font.pixelSize:12}
    GGText { colorKey: "ui.MarketPriceChart.5";anchors.centerIn:parent;width:parent.width-40;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.WordWrap;visible:!root.plottable;text:root.observed && root.prices.length ? root.prices.length+" prisobservationer · historik byggs upp\nSenast "+Format.money(root.prices[root.prices.length-1]) : "Prishistorik saknas";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:12}
}
