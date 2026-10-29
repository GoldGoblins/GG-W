import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Canvas {
    id:root
    objectName:"tokenSparkline"
    property var samples:[]
    property string periodLabel:"7 dagar"
    property string sourceLabel:"CoinGecko"
    property bool stale:false
    readonly property bool available:samples.length>=2 && samples.length<=600 && samples.every(function(n){return typeof n==="number" && isFinite(n) && n>=0})
    readonly property color trendColor:!available || samples[samples.length-1]===samples[0] ? RuntimeTheme.GGTheme.muted : samples[samples.length-1]>samples[0] ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.negative
    onSamplesChanged:requestPaint()
    onWidthChanged:requestPaint()
    onHeightChanged:requestPaint()
    onStaleChanged:requestPaint()
    onPaint:{
        var c=getContext("2d");c.reset()
        if(!available || width<8 || height<8)return
        var low=Math.min.apply(null,samples),high=Math.max.apply(null,samples),span=high-low
        function y(value){return span===0 ? height/2 : height-4-(value-low)*(height-8)/span}
        c.strokeStyle=RuntimeTheme.GGTheme.line;c.lineWidth=0.6;c.setLineDash([2,3]);c.beginPath();c.moveTo(3,y(samples[0]));c.lineTo(width-3,y(samples[0]));c.stroke();c.setLineDash([])
        c.globalAlpha=stale ? 0.5 : 0.9;c.strokeStyle=trendColor;c.lineWidth=1.35;c.lineJoin="round";c.lineCap="round";c.beginPath()
        for(var i=0;i<samples.length;i++){var x=3+i*(width-6)/(samples.length-1);if(i===0)c.moveTo(x,y(samples[i]));else c.lineTo(x,y(samples[i]))}
        c.stroke()
    }
    GGText { colorKey: "ui.PriceSparkline.1";anchors.centerIn:parent;visible:!root.available;text:"—";color:RuntimeTheme.GGTheme.dim;font.pixelSize:11}
    HoverHandler {id:hover}
    ToolTip.visible:hover.hovered
    ToolTip.delay:500
    ToolTip.text:!available ? "Prishistorik saknas" : periodLabel+" · "+sourceLabel+(stale ? " · äldre data" : "")+"\nHistoriska prisobservationer, inte realtid eller OHLC."
    Accessible.role:Accessible.Graphic
    Accessible.name:available ? periodLabel+" · "+sourceLabel : "Prishistorik saknas"
}
