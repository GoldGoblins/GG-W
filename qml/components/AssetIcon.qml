
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// Presentation only. A ticker never selects another asset's network logo.
Item {
    id:root;objectName:"assetIdentityIcon";implicitWidth:32;implicitHeight:32
    property string symbol:""
    property string assetId:""
    property string chainId:""
    property string assetNamespace:""
    property string assetReference:""
    property string sourceUrl:""
    readonly property string logoKey:({
        "bip122:000000000019d6689c085ae165831e93/native:BTC":"btc",
        "eip155:1/native:ETH":"eth","eip155:10/native:ETH":"eth","eip155:8453/native:ETH":"eth","eip155:42161/native:ETH":"eth",
        "eip155:56/native:BNB":"bnb","eip155:43114/native:AVAX":"avax","eip155:137/native:POL":"pol",
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp/native:SOL":"sol",
        "kaspa:mainnet/native:KAS":"kas","tron:mainnet/native:TRX":"trx","cardano:mainnet/native:ADA":"ada",
        "coingecko:bitcoin":"btc","coingecko:ethereum":"eth","coingecko:solana":"sol","coingecko:kaspa":"kas",
        "coingecko:binancecoin":"bnb","coingecko:avalanche-2":"avax","coingecko:matic-network":"pol","coingecko:polygon-ecosystem-token":"pol",
        "coingecko:tron":"trx","coingecko:cardano":"ada","coingecko:usd-coin":"usdc","coingecko:tether":"usdt"
    })[assetId] || ""
    readonly property bool localImage:{var base=String(Qt.resolvedUrl("../assets/"));return sourceUrl.indexOf(base)===0 && /^[A-Za-z0-9_-]+\.(png|webp|svg)$/i.test(sourceUrl.slice(base.length))}
    readonly property color badgeColor:({btc:"#f7931a",usdc:"#2775ca",usdt:"#26a17b",kas:"#70c7ba",avax:"#e84142",pol:"#8247e5"})[logoKey] || RuntimeTheme.GGTheme.panel
    Rectangle {anchors.fill:parent;radius:width/2;color:root.badgeColor;border.color:root.logoKey ? "transparent" : RuntimeTheme.GGTheme.line}
    Image {id:provided;anchors.fill:parent;visible:root.localImage && status===Image.Ready;source:root.localImage ? root.sourceUrl : "";sourceSize.width:Math.ceil(root.width*2);sourceSize.height:Math.ceil(root.height*2);fillMode:Image.PreserveAspectFit;asynchronous:true}
    Canvas {
        id:mark;anchors.fill:parent;visible:!provided.visible && ["eth","sol","bnb","pol","trx","ada","avax","kas","usdc","usdt"].indexOf(root.logoKey)>=0
        onWidthChanged:requestPaint();onHeightChanged:requestPaint();onVisibleChanged:requestPaint()
        Connections {target:root;function onLogoKeyChanged(){mark.requestPaint()}}
        onPaint:{
            var c=getContext("2d");c.reset();c.scale(width/32,height/32)
            function polygon(points,color){c.fillStyle=color;c.beginPath();c.moveTo(points[0][0],points[0][1]);for(var i=1;i<points.length;i++)c.lineTo(points[i][0],points[i][1]);c.closePath();c.fill()}
            if(root.logoKey==="eth"){
                polygon([[16,2],[7,17],[16,21]],"#aeb8d0");polygon([[16,2],[16,21],[25,17]],"#737e9b")
                polygon([[7,19],[16,30],[16,23]],"#aeb8d0");polygon([[25,19],[16,30],[16,23]],"#737e9b")
            }else if(root.logoKey==="sol"){
                var gradient=c.createLinearGradient(3,27,29,4);gradient.addColorStop(0,"#9945ff");gradient.addColorStop(.5,"#5ca2d5");gradient.addColorStop(1,"#14f195")
                polygon([[7,6],[29,6],[24,11],[2,11]],gradient);polygon([[2,13],[24,13],[29,18],[7,18]],gradient);polygon([[7,20],[29,20],[24,25],[2,25]],gradient)
            }else if(root.logoKey==="bnb"){
                polygon([[16,3],[10,9],[13,12],[16,9],[19,12],[22,9]],"#f3ba2f");polygon([[16,29],[10,23],[13,20],[16,23],[19,20],[22,23]],"#f3ba2f")
                polygon([[3,16],[7,12],[11,16],[7,20]],"#f3ba2f");polygon([[21,16],[25,12],[29,16],[25,20]],"#f3ba2f");polygon([[12,16],[16,12],[20,16],[16,20]],"#f3ba2f")
            }else if(root.logoKey==="avax"){
                polygon([[15,7],[6,23],[14,23],[19,14]],RuntimeTheme.GGTheme.bright);polygon([[23,16],[19,23],[27,23]],RuntimeTheme.GGTheme.bright)
            }else if(root.logoKey==="trx"){
                c.strokeStyle="#ed3439";c.lineWidth=1.5;c.beginPath();c.moveTo(5,5);c.lineTo(28,9);c.lineTo(14,28);c.closePath();c.moveTo(5,5);c.lineTo(19,13);c.lineTo(28,9);c.moveTo(19,13);c.lineTo(14,28);c.stroke()
            }else if(root.logoKey==="ada"){
                c.fillStyle="#3a83d9";for(var ring=0;ring<3;ring++){var n=ring===0 ? 6 : 12;for(var j=0;j<n;j++){var a=j*Math.PI*2/n+(ring%2)*.25,r=5+ring*5;c.beginPath();c.arc(16+Math.cos(a)*r,16+Math.sin(a)*r,ring===0 ? 1.5 : ring===1 ? 1.1 : .7,0,Math.PI*2);c.fill()}}
            }else if(root.logoKey==="pol"){
                c.strokeStyle=RuntimeTheme.GGTheme.bright;c.lineWidth=2.1;c.lineJoin="round";c.beginPath();c.moveTo(7,12);c.lineTo(12,9);c.lineTo(17,12);c.lineTo(17,18);c.lineTo(12,21);c.lineTo(7,18);c.closePath();c.moveTo(15,14);c.lineTo(20,11);c.lineTo(25,14);c.lineTo(25,20);c.lineTo(20,23);c.lineTo(15,20);c.stroke()
            }else if(root.logoKey==="kas"){
                c.strokeStyle=RuntimeTheme.GGTheme.bright;c.lineWidth=2.5;c.beginPath();c.moveTo(10,7);c.lineTo(10,25);c.moveTo(22,8);c.lineTo(12,16);c.lineTo(22,24);c.moveTo(5,16);c.lineTo(12,16);c.stroke()
            }else if(root.logoKey==="usdc"){
                c.strokeStyle=RuntimeTheme.GGTheme.bright;c.lineWidth=1.5;c.beginPath();c.arc(16,16,10,-1.15,1.15);c.stroke();c.beginPath();c.arc(16,16,10,2,4.3);c.stroke()
            }else if(root.logoKey==="usdt"){
                c.fillStyle=RuntimeTheme.GGTheme.bright;c.fillRect(8,8,16,4);c.fillRect(14,12,4,13);c.strokeStyle=RuntimeTheme.GGTheme.bright;c.lineWidth=1.2;c.beginPath();c.ellipse(5,13,22,5);c.stroke()
            }
        }
    }
    GGText { colorKey: "ui.AssetIcon.1";
        anchors.centerIn:parent;visible:!provided.visible && (!root.logoKey || root.logoKey==="btc" || root.logoKey==="usdc")
        text:root.logoKey==="btc" ? "₿" : root.logoKey==="usdc" ? "$" : root.symbol.slice(0,1).toUpperCase() || "◇"
        color:root.logoKey ? "white" : RuntimeTheme.GGTheme.bright;font.family:root.logoKey ? "Segoe UI Symbol" : "monospace";font.bold:true;font.pixelSize:root.width*(root.logoKey ? .72 : .48)
    }
    Accessible.role:Accessible.Graphic
    Accessible.name:root.symbol+(root.logoKey ? " · symbol för identifierad tillgång" : " · bokstavsmärke, logotyp saknas")
}
