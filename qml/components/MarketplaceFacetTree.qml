import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

ListView {
    id:root;objectName:"marketCategoryNavigation"
    property var rows:[]
    property string kind:""
    property string category:""
    property string material:""
    property string collection:""
    property string origin:""
    property string maker:""
    property bool busy:false
    property var collapsed:({collections:true,origin:true,maker:true})
    readonly property var categoryNames:({ITEM:"Föremål",MATERIAL:"Material",ART:"Konst",COLLECTIBLE:"Samlarobjekt",DOCUMENT:"Dokument",TOOL:"Verktyg",COMPONENT:"Komponenter",SERVICE:"Tjänster"})
    readonly property var materialNames:({WOOD:"Trä",METAL:"Metall",STONE:"Sten",FABRIC:"Textil",DIGITAL:"Digitalt",MIXED:"Blandat",UNKNOWN:"Ej angivet",GOLD:"Guld",SILVER:"Silver",COPPER:"Koppar"})
    readonly property var categoryRows:choices(rows,"category",categoryNames)
    readonly property var materialRows:materialChoices()
    readonly property var nodes:build()
    signal filterRequested(string field,string value,string kind)
    function choices(source,field,names){var counts=Object.create(null);source.forEach(function(row){var value=row[field];if(value)counts[value]=(counts[value] || 0)+1});return Object.keys(counts).sort().map(function(value){return {id:value,name:Object.prototype.hasOwnProperty.call(names,value) ? names[value] : value,count:counts[value]}})}
    function materialChoices(){var counts=Object.create(null);rows.forEach(function(row){var values=Object.create(null);if(row.material)values[row.material]=true;(row.composition || []).forEach(function(part){if(part.symbol)values[part.symbol]=true});Object.keys(values).forEach(function(value){counts[value]=(counts[value] || 0)+1})});return Object.keys(counts).sort().map(function(value){return {id:value,name:Object.prototype.hasOwnProperty.call(materialNames,value) ? materialNames[value] : value,count:counts[value]}})}
    function group(result,id,label,source,field,names,kind,allLabel){
        result.push({id:id,type:"heading",label:label,count:source.length,depth:0})
        if(collapsed[id])return
        result.push({id:id+"-all",type:"choice",field:field,value:"",kind:kind,label:allLabel,count:source.length,depth:1});
        (id==="materials" ? materialRows : choices(source,field,names)).forEach(function(row){if(id!=="services" || row.id!=="SERVICE")result.push({id:row.id,type:"choice",field:field,value:row.id,kind:kind,label:row.name,count:row.count,depth:1})})
    }
    function build(){
        var result=[]
        group(result,"objects","FÖREMÅL",rows.filter(function(r){return r.kind!=="SERVICE"}),"category",categoryNames,"OBJECTS","Alla föremål")
        group(result,"services","TJÄNSTER",rows.filter(function(r){return r.kind==="SERVICE"}),"category",categoryNames,"SERVICE","Alla tjänster")
        group(result,"materials","MATERIAL",rows,"material",materialNames,"","Alla material")
        var collections=rows.filter(function(r){return !!r.collection_name})
        if(collections.length)group(result,"collections","SAMLINGAR",collections,"collection_name",{},"","Alla samlingar")
        var origins=rows.filter(function(r){return !!r.origin})
        if(origins.length)group(result,"origin","URSPRUNG",origins,"origin",{},"","Alla ursprung")
        var makers=rows.filter(function(r){return !!r.maker})
        if(makers.length)group(result,"maker","PRODUCENT",makers,"maker",{},"","Alla producenter")
        return result
    }
    function selected(node){
        if(node.type!=="choice")return false
        if(node.field==="all")return !kind && !category && !material && !collection && !origin && !maker
        if(node.field==="category")return kind===node.kind && category===node.value
        if(node.field==="material")return material===node.value
        if(node.field==="collection_name")return collection===node.value
        if(node.field==="origin")return origin===node.value
        return maker===node.value
    }
    function activate(node){
        if(busy)return
        if(node.type==="heading"){var next=Object.assign({},collapsed);next[node.id]=!collapsed[node.id];collapsed=next}
        else filterRequested(node.field,node.value,node.kind)
    }
    model:nodes;clip:true;boundsBehavior:Flickable.StopAtBounds;spacing:0;cacheBuffer:80
    header:Item {width:root.width;height:30
        GGText { colorKey: "ui.MarketplaceFacetTree.1";height:parent.height;text:"KATEGORIER";font.family:"monospace";font.pixelSize:10;verticalAlignment:Text.AlignVCenter;color:RuntimeTheme.GGTheme.muted;font.letterSpacing:.7}
        CryptoButton { property string uiColorScope: "ui.control.MarketplaceFacetTree.1";anchors.right:parent.right;visible:!!(root.kind || root.category || root.material || root.collection || root.origin || root.maker);height:26;implicitWidth:42;text:"Alla";flat:true;quiet:true;enabled:!root.busy;onClicked:root.filterRequested("all","","")}
    }
    ScrollBar.vertical:ScrollBar {}
    delegate:Rectangle {
        id:entry;required property var modelData
        objectName:modelData.type==="heading" ? "marketFacetGroup" : modelData.field==="material" ? "marketMaterialChoice" : "marketCategoryChoice"
        width:root.width;height:modelData.type==="heading" ? 28 : 22
        readonly property bool selected:root.selected(modelData)
        color:selected ? RuntimeTheme.GGTheme.selected : hover.containsMouse ? RuntimeTheme.GGTheme.hover : "transparent"
        Rectangle { GGColorTarget { colorKey: "ui.fill.MarketplaceFacetTree.1"; }x:0;y:3;width:3;height:parent.height-6;visible:entry.selected;color:RuntimeTheme.GGTheme.accent}
        GGText { colorKey: "ui.MarketplaceFacetTree.2";x:entry.modelData.depth ? 3 : 0;y:0;width:16;height:parent.height;verticalAlignment:Text.AlignVCenter;text:entry.modelData.type==="heading" ? (root.collapsed[entry.modelData.id] ? "›" : "⌄") : entry.modelData.depth ? "├" : "";color:entry.selected ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:13}
        GGText { colorKey: "ui.MarketplaceFacetTree.3";x:18;y:0;width:parent.width-47;height:parent.height;text:entry.modelData.label;color:entry.selected || entry.modelData.type==="heading" ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:root.width>=190 ? (entry.modelData.type==="heading" ? 13 : 12) : (entry.modelData.type==="heading" ? 11 : 10);verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight;textFormat:Text.PlainText;font.letterSpacing:entry.modelData.type==="heading" ? .6 : 0}
        GGText { colorKey: "ui.MarketplaceFacetTree.4";anchors.right:parent.right;anchors.rightMargin:4;height:parent.height;text:entry.modelData.count;color:entry.selected ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.dim;font.family:"monospace";font.pixelSize:10;verticalAlignment:Text.AlignVCenter}
        MouseArea {id:hover;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;enabled:!root.busy;onClicked:root.activate(entry.modelData)}
        activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:modelData.label+" · "+modelData.count
        Keys.onReturnPressed:root.activate(modelData)
        Keys.onSpacePressed:root.activate(modelData)
        ToolTip.visible:hover.containsMouse;ToolTip.text:modelData.label;ToolTip.delay:700
    }
}
